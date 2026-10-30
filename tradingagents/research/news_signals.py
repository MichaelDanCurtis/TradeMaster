"""Versioned news evidence and causal snapshots; no execution authority.

Historical current-version archives are retrospective proxies. Only an observed
snapshot requires this machine's receipt and inference completion timestamps.
Text tone is not an expected return or an issuer-specific event interpretation.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

VERSION = "news_signals_v1"
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")
EVENTS = {"earnings_guidance", "financing", "legal_regulatory", "commercial",
          "management", "macro", "other"}


def timestamp(value: str) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("A timezone-qualified timestamp is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Naive timestamps are not accepted")
    return parsed.astimezone(timezone.utc)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def normalize_article(raw: dict, retrieved_at: str, source_sha256: str) -> dict:
    """Missing timestamps/identities are quarantined by the caller, never guessed."""
    published = timestamp(raw["created_at"])
    revised = timestamp(raw["updated_at"])
    received = timestamp(retrieved_at)
    if revised < published or max(published, revised) > received:
        raise ValueError("Inconsistent article timestamps")
    if not re.fullmatch(r"[a-f0-9]{64}", source_sha256):
        raise ValueError("Invalid capture digest")
    headline = raw.get("headline")
    if not isinstance(headline, str) or not headline.strip() or len(headline) > 10000:
        raise ValueError("Missing or oversized headline")
    identifier = str(raw.get("id", ""))
    if not identifier or len(identifier) > 160:
        raise ValueError("Missing article identity")
    symbols = raw.get("symbols")
    if not isinstance(symbols, list) or not symbols or any(
        not isinstance(s, str) or not SYMBOL.fullmatch(s) for s in symbols
    ):
        raise ValueError("Unverified ticker tags")
    url = urlsplit(raw.get("url", ""))
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
        raise ValueError("Missing public article URL")
    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Missing publisher")
    # Alpaca distributes Benzinga; domains are not independent corroborations.
    row = {"schema_version": VERSION, "provider": "alpaca", "article_id": identifier,
           "headline": headline.strip(), "symbols": sorted(set(symbols)),
           "url": urlunsplit((url.scheme, url.netloc, url.path, "", "")),
           "source": source, "source_family": "benzinga_distribution",
           "published_at": published.isoformat(), "updated_at": revised.isoformat(),
           "retrieved_at": received.isoformat(), "source_sha256": source_sha256,
           "text_scope": "headline_only", "issuer_identity": "provider_ticker_tag_only"}
    row["version_id"] = digest({k: v for k, v in row.items()
                                if k not in {"retrieved_at", "source_sha256"}})
    return row


def validate_tone(row: dict, article: dict) -> dict:
    """Validate a local classifier result. Probabilities describe text labels."""
    if row.get("version_id") != article["version_id"]:
        raise ValueError("Tone belongs to another article version")
    scores = row.get("probabilities", {})
    if set(scores) != {"positive", "negative", "neutral"}:
        raise ValueError("Three text-label probabilities required")
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or
           not math.isfinite(v) or not 0 <= v <= 1 for v in scores.values()):
        raise ValueError("Invalid text probability")
    if not math.isclose(sum(scores.values()), 1, abs_tol=1e-5):
        raise ValueError("Text probabilities must sum to one")
    if timestamp(row["completed_at"]) < timestamp(article["retrieved_at"]):
        raise ValueError("Inference predates article capture")
    if not row.get("model") or not re.fullmatch(r"[a-f0-9]{40}", row.get("revision", "")):
        raise ValueError("Pinned classifier identity required")
    return row


def normalize_web_excerpt(*, url: str, symbol: str, excerpt: str, publication_date: str,
                          retrieved_at: str, source_sha256: str) -> dict:
    """A current web crawl is observed evidence only, including old dated pages.

    Preserve day precision explicitly. Publication availability uses end of that
    UTC date conservatively, but never substitutes for receipt of the page.
    Caller must separately establish the issuer; URL text is not proof of identity.
    """
    day = date.fromisoformat(publication_date)
    received = timestamp(retrieved_at)
    if day > received.date():
        raise ValueError("Future publication date")
    if not SYMBOL.fullmatch(symbol) or not isinstance(excerpt, str) or not 1 <= len(excerpt) <= 10000:
        raise ValueError("Invalid web excerpt")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid source URL")
    if not re.fullmatch(r"[a-f0-9]{64}", source_sha256):
        raise ValueError("Invalid source hash")
    row = {"schema_version": VERSION, "provider": "web_agent", "article_id": digest(url),
           "headline": excerpt, "text_scope": "captured_excerpt", "symbols": [symbol],
           "url": url, "source": parsed.hostname, "source_family": parsed.hostname,
           "publication_date": publication_date, "publication_precision": "day",
           "published_at": datetime.combine(day + timedelta(days=1), datetime.min.time(), timezone.utc).isoformat(),
           "updated_at": received.isoformat(), "retrieved_at": received.isoformat(),
           "source_sha256": source_sha256, "issuer_identity": "agent_selected_requires_review",
           "allowed_modes": ["observed"]}
    row["version_id"] = digest(row)
    return row


def validate_agent_evidence(row: dict, article: dict) -> dict:
    """Bound agent output to cited text; this does not certify its interpretation."""
    required = {"version_id", "symbol", "event_type", "direction", "relevance",
                "passages", "completed_at", "extractor", "prompt_sha256"}
    if set(row) != required or row["version_id"] != article["version_id"]:
        raise ValueError("Unexpected agent schema or article version")
    if row["symbol"] not in article["symbols"] or row["event_type"] not in EVENTS:
        raise ValueError("Unsupported issuer or event category")
    if row["direction"] not in {"positive", "negative", "mixed", "unknown"}:
        raise ValueError("Unsupported direction")
    if row["relevance"] not in {"direct", "indirect", "unknown"}:
        raise ValueError("Unsupported relevance")
    if timestamp(row["completed_at"]) < timestamp(article["retrieved_at"]):
        raise ValueError("Extraction predates capture")
    if not isinstance(row["extractor"], str) or not row["extractor"].strip() or not re.fullmatch(r"[a-f0-9]{64}", row["prompt_sha256"]):
        raise ValueError("Extraction provenance required")
    passages = row["passages"]
    if not isinstance(passages, list) or not 1 <= len(passages) <= 5:
        raise ValueError("Supporting passages required")
    for passage in passages:
        if set(passage) != {"start", "end", "quote"}:
            raise ValueError("Unexpected passage fields")
        start, end = passage["start"], passage["end"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(article["headline"]):
            raise ValueError("Invalid evidence span")
        if article["headline"][start:end] != passage["quote"]:
            raise ValueError("Unsupported evidence quote")
    return row


def available_at(article: dict, mode: str, tone=None, latency_minutes=15) -> datetime:
    if mode not in {"observed", "retrospective_proxy"}:
        raise ValueError("Unknown evidence mode")
    if mode not in article.get("allowed_modes", ["observed", "retrospective_proxy"]):
        raise ValueError("Current web evidence cannot be backdated into a historical proxy")
    if not isinstance(latency_minutes, (int, float)) or not math.isfinite(latency_minutes) or latency_minutes < 0:
        raise ValueError("Invalid decision latency")
    times = [timestamp(article["published_at"]), timestamp(article["updated_at"])]
    if mode == "observed":
        times.append(timestamp(article["retrieved_at"]))
        if tone is not None:
            times.append(timestamp(tone["completed_at"]))
    return max(times) + timedelta(minutes=latency_minutes)


def _tokens(headline):
    # Keep numbers and negation: revisions that change either must stay distinct.
    return tuple(re.findall(r"[a-z0-9]+", headline.casefold()))


def deduplicate(articles: list[dict]) -> list[dict]:
    """Collapse exact normalized headline repetitions within 24h, past rows only.

    This is a conservative headline-cluster proxy, not complete event resolution.
    """
    result = []
    for article in sorted(articles, key=lambda a: (a["published_at"], a["version_id"])):
        words = _tokens(article["headline"])
        duplicate = False
        for earlier in reversed(result):
            delta = timestamp(article["published_at"]) - timestamp(earlier["published_at"])
            if delta > timedelta(hours=24):
                break
            if words == _tokens(earlier["headline"]):
                duplicate = True
                break
        if not duplicate:
            result.append(article)
    return result


def snapshot(articles: list[dict], tones: dict, symbol: str, cutoff: str,
             *, mode="observed", window_days=7, latency_minutes=15,
             coverage_complete=False) -> dict:
    """Build one causal issuer snapshot. Coverage supplied by verified collector."""
    if not SYMBOL.fullmatch(symbol) or type(window_days) is not int or not 1 <= window_days <= 365:
        raise ValueError("Invalid symbol or news window")
    end = timestamp(cutoff)
    start = end - timedelta(days=window_days)
    latest = {}
    for article in articles:
        if symbol not in article["symbols"]:
            continue
        at = available_at(article, mode, latency_minutes=latency_minutes)
        if at >= end:
            continue
        key = (article["provider"], article["article_id"])
        previous = latest.get(key)
        if previous and previous["updated_at"] == article["updated_at"] and previous["version_id"] != article["version_id"]:
            raise ValueError("Conflicting article versions at the same revision time")
        if previous is None or (article["updated_at"], article["retrieved_at"]) > (previous["updated_at"], previous["retrieved_at"]):
            latest[key] = article
    candidates = [a for a in latest.values()
                  if start <= available_at(a, mode, latency_minutes=latency_minutes) < end]
    clusters = deduplicate(candidates)
    scored = []
    for article in clusters:
        tone = tones.get(article["version_id"])
        # Document tone cannot resolve conflicting effects on multiple issuers.
        if tone is None or article["symbols"] != [symbol]:
            continue
        validate_tone(tone, article)
        if available_at(article, mode, tone, latency_minutes) >= end:
            continue
        p = tone["probabilities"]
        scored.append({"version_id": article["version_id"],
                       "tone": p["positive"] - p["negative"],
                       "label": max(p, key=p.get)})
    label_counts = Counter(s["label"] for s in scored)
    state = "endpoint_complete" if coverage_complete else "incomplete"
    # Counts describe observed records; no-news is not neutral sentiment.
    return {"schema_version": VERSION, "symbol": symbol, "cutoff": end.isoformat(),
            "mode": mode, "window_days": window_days, "latency_minutes": latency_minutes,
            "coverage": state, "article_count": len(candidates), "headline_cluster_count": len(clusters),
            "duplicates_removed": len(candidates) - len(clusters),
            "distribution_family_count": len({a["source_family"] for a in clusters}),
            "scored_single_ticker_count": len(scored),
            "positive_count": label_counts["positive"], "negative_count": label_counts["negative"],
            "neutral_count": label_counts["neutral"],
            "unscored_count": len(clusters) - len(scored),
            "mean_headline_tone": sum(s["tone"] for s in scored) / len(scored) if scored else None,
            "negative_label_fraction": label_counts["negative"] / len(scored) if scored else None,
            "hours_since_latest": (end - max(available_at(a, mode, latency_minutes=latency_minutes)
                                               for a in clusters)).total_seconds() / 3600 if clusters else None,
            "version_ids": [a["version_id"] for a in clusters], "scored": scored,
            "qualified_for_return_claim": False}


def agent_snapshot(articles: list[dict], evidence: list[dict], symbol: str,
                   cutoff: str, *, latency_minutes=15) -> dict:
    """Quantify observed agent labels separately from document classifier tone.

    All supporting excerpts must be validated. These are counts of collected
    evidence, not claims that the events occurred today or independent news.
    """
    end = timestamp(cutoff)
    if not SYMBOL.fullmatch(symbol):
        raise ValueError("Invalid symbol")
    by_id = {a["version_id"]: a for a in articles}
    usable, labels = [], {}
    for row in evidence:
        article = by_id[row["version_id"]]
        validate_agent_evidence(row, article)
        if row["symbol"] != symbol or available_at(article, "observed", row, latency_minutes) >= end:
            continue
        if row["version_id"] in labels and labels[row["version_id"]] != row:
            raise ValueError("Conflicting agent labels")
        if row["version_id"] not in labels:
            usable.append(article)
        labels[row["version_id"]] = row
    unique = deduplicate(usable)
    counts = Counter(labels[a["version_id"]]["direction"] for a in unique)
    direct = [labels[a["version_id"]] for a in unique if labels[a["version_id"]]["relevance"] == "direct"]
    signed = [{"positive": 1, "negative": -1, "mixed": 0}[r["direction"]]
              for r in direct if r["direction"] != "unknown"]
    return {"symbol": symbol, "cutoff": cutoff, "mode": "observed", "collected_evidence_count": len(unique),
            "direction_counts": {k: counts[k] for k in ["positive", "negative", "mixed", "unknown"]},
            "event_counts": dict(Counter(r["event_type"] for r in direct)),
            "mean_direction_label": sum(signed) / len(signed) if signed else None,
            "publication_dates": [a.get("publication_date", a["published_at"][:10]) for a in unique],
            "version_ids": [a["version_id"] for a in unique],
            "meaning": "Uncalibrated qualitative labels of collected evidence; not return estimates or new-event counts."}
