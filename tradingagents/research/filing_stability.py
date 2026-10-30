"""Original-filing stability primitives. No prices, network, LLM or broker access."""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import re
import warnings
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning


VERSION = "filing_stability_v1"
# Fixed locally: changing this list creates a different research specification.
STOP_WORDS = frozenset("""a an and are as at be been being but by can could did do does
doing for from had has have having he her here hers herself him himself his how i if
in into is it its itself me more most my myself no nor not of off on once only or
other our ours ourselves out over own same she should so some such than that the
their theirs them themselves then there these they this those through to too under
until up very was we were what when where which while who whom why will with would
you your yours yourself yourselves""".split())


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("An explicit timestamp offset is required")
    return result.astimezone(timezone.utc)


def conservative_public_time(record: dict) -> datetime:
    """Filing-date end avoids claiming acceptance always means dissemination."""
    accepted = timestamp(record["acceptanceDateTime"])
    filed = date.fromisoformat(record["filingDate"])
    end = datetime.combine(filed, time(23, 59, 59), ZoneInfo("America/New_York"))
    return max(accepted, end.astimezone(timezone.utc))


def earliest_entry(record: dict, sessions: list[dict], *, mode="historical",
                   received_at=None, completed_at=None, processing_seconds=300,
                   completed_session_delay=2) -> str | None:
    """Caller supplies exchange sessions including actual holidays and closures."""
    if processing_seconds < 0 or completed_session_delay < 0:
        raise ValueError("Negative delay")
    known = conservative_public_time(record)
    if mode == "historical":
        known += timedelta(seconds=processing_seconds)
    elif mode == "forward":
        if received_at is None or completed_at is None:
            raise ValueError("Forward decisions require actual receipt and completion")
        known = max(known, timestamp(received_at), timestamp(completed_at))
    else:
        raise ValueError("Unknown availability mode")
    opens = [timestamp(x["open"]) for x in sessions]
    closes = [timestamp(x["close"]) for x in sessions]
    if (opens != sorted(set(opens)) or closes != sorted(set(closes))
            or any(o >= c for o, c in zip(opens, closes))
            or any(c >= o for c, o in zip(closes, opens[1:]))):
        raise ValueError("Invalid exchange sessions")
    # Only sessions opening after availability count as full processing sessions.
    index = bisect_right(opens, known) + completed_session_delay
    return opens[index].isoformat() if index < len(opens) else None


def submission_rows(payload: dict, cik: str) -> list[dict]:
    columns = payload.get("filings", {}).get("recent", payload)
    if "accessionNumber" not in columns:
        raise ValueError("Not a SEC submissions array")
    count = len(columns["accessionNumber"])
    keys = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime",
            "form", "primaryDocument", "items"]
    for key in keys:
        if key in columns and len(columns[key]) != count:
            raise ValueError("Misaligned SEC submission columns")
    result = []
    for i in range(count):
        record = {k: columns[k][i] if k in columns else "" for k in keys}
        record["cik"] = str(int(cik)).zfill(10)
        result.append(record)
    return result


def original_pairs(records: list[dict], *, report_year=2024, limit_per_issuer=4):
    """Metadata candidates only; fiscal identity is checked against original HTML."""
    by_accession = {}
    for r in records:
        accession = r["accessionNumber"]
        if accession in by_accession and by_accession[accession] != r:
            raise ValueError("Conflicting accession metadata")
        by_accession[accession] = r
    originals = [r for r in by_accession.values() if r["form"] in {"10-K", "10-Q"}
                 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["reportDate"])]
    by_period = {}
    for r in originals:
        by_period.setdefault((r["cik"], r["form"], r["reportDate"]), []).append(r)
    newer = [r for r in originals if r["reportDate"].startswith(str(report_year) + "-")]
    selected, counts = [], {}
    for new in sorted(newer, key=lambda r: (r["cik"], r["reportDate"], r["accessionNumber"])):
        cik = new["cik"]
        if counts.get(cik, 0) >= limit_per_issuer:
            continue
        counts[cik] = counts.get(cik, 0) + 1
        candidates = [old for old in originals if old["cik"] == cik and old["form"] == new["form"]
                      and 350 <= (date.fromisoformat(new["reportDate"]) -
                                  date.fromisoformat(old["reportDate"])).days <= 380]
        reasons = []
        if len(by_period[(cik, new["form"], new["reportDate"])]) != 1:
            reasons.append("ambiguous_original_new_period")
        if len(candidates) != 1:
            reasons.append("missing_or_ambiguous_prior_period")
        old = candidates[0] if len(candidates) == 1 else None
        if old and old["filingDate"] >= new["filingDate"]:
            reasons.append("prior_document_not_previously_filed")
        selected.append({"new": new, "old": old, "metadata_issues": reasons})
    return selected


def document_url(record: dict, *, full_submission=False) -> str:
    cik = str(int(record["cik"]))
    accession = record["accessionNumber"]
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
        raise ValueError("Invalid accession")
    if full_submission:
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}.txt"
    name = record["primaryDocument"]
    if (not re.fullmatch(r"[a-zA-Z0-9_./-]+", name)
            or any(p in {"", ".", ".."} for p in name.split("/"))):
        raise ValueError("Invalid primary-document path")
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{name}"


def normalized_document(raw: bytes) -> dict:
    # Inline XBRL is XHTML; HTML recovery is deliberate for older issuer markup.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(raw, "lxml")
    fields = {}
    for node in soup.find_all(attrs={"name": True}):
        name = str(node.get("name", "")).lower()
        if name.startswith("dei:"):
            fields.setdefault(name.split(":", 1)[1], set()).add(node.get_text(" ", strip=True))
    dei_raw = {key: sorted(value) for key, value in fields.items()}
    dei = dict(dei_raw)
    normalized_dates = set()
    for value in dei.get("documentperiodenddate", []):
        cleaned = re.sub(r"\s+", " ", value).strip().replace(" ,", ",")
        for pattern in ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"]:
            try:
                normalized_dates.add(datetime.strptime(cleaned, pattern).date().isoformat())
                break
            except ValueError:
                continue
        else:
            normalized_dates.add(value)
    if normalized_dates:
        dei["documentperiodenddate"] = sorted(normalized_dates)
    before = len(soup.get_text(" ", strip=True))
    # Extract DEI first: it may be stored in the invisible inline XBRL header.
    for node in list(soup.find_all(True)):
        if node.parent is None:
            continue
        name = (node.name or "").lower()
        style = re.sub(r"\s+", "", str(node.get("style", "")).lower())
        if (name in {"table", "script", "style", "noscript", "head", "ix:header", "ix:hidden"}
                or "display:none" in style or "visibility:hidden" in style
                or node.has_attr("hidden")):
            node.decompose()
    text = soup.get_text(" ", strip=True)
    tokens = sorted(set(re.findall(r"[a-z]{2,}", text.lower())) - STOP_WORDS)
    return {"version": VERSION, "raw_sha256": sha_bytes(raw), "dei": dei, "dei_raw": dei_raw,
            "characters_before": before, "characters_after": len(text),
            "distinct_tokens": len(tokens), "tokens_sha256": sha_bytes("\n".join(tokens).encode()),
            "tokens": tokens, "preview": text[:600]}


def _one(doc: dict, key: str):
    values = doc["dei"].get(key, [])
    return values[0] if len(values) == 1 else None


def validate_document(doc: dict, record: dict) -> list[str]:
    issues = []
    if doc["distinct_tokens"] < 500 or doc["characters_after"] < 10000:
        issues.append("insufficient_narrative_after_table_removal")
    for key, expected in [("documenttype", record["form"]),
                          ("documentperiodenddate", record["reportDate"])]:
        if _one(doc, key) != expected:
            issues.append("missing_or_mismatched_" + key)
    cik = _one(doc, "entitycentralindexkey")
    if not cik or not cik.isdigit() or int(cik) != int(record["cik"]):
        issues.append("missing_or_mismatched_issuer_cik")
    if _one(doc, "documentfiscalperiodfocus") not in {"Q1", "Q2", "Q3", "FY"}:
        issues.append("missing_fiscal_period")
    fy = _one(doc, "documentfiscalyearfocus")
    if not fy or not re.fullmatch(r"\d{4}", fy):
        issues.append("missing_fiscal_year")
    try:
        conservative_public_time(record)
    except (ValueError, KeyError, TypeError):
        issues.append("invalid_historical_availability")
    return issues


def score_pair(pair: dict, new: dict, old: dict) -> dict:
    issues = list(pair["metadata_issues"])
    issues += ["new:" + x for x in validate_document(new, pair["new"])]
    issues += ["old:" + x for x in validate_document(old, pair["old"])]
    if _one(new, "documentfiscalperiodfocus") != _one(old, "documentfiscalperiodfocus"):
        issues.append("fiscal_period_mismatch")
    try:
        if int(_one(new, "documentfiscalyearfocus")) != int(_one(old, "documentfiscalyearfocus")) + 1:
            issues.append("fiscal_year_not_consecutive")
    except (ValueError, TypeError):
        issues.append("unqualified_fiscal_year_pair")
    a, b = set(new["tokens"]), set(old["tokens"])
    return {"status": "unqualified" if issues else "structurally_validated",
            "issues": issues, "jaccard": len(a & b) / len(a | b) if not issues and a | b else None,
            "new_tokens": len(a), "old_tokens": len(b), "intersection": len(a & b),
            "union": len(a | b), "scope": "Unsigned text stability; no return prediction or investment qualification"}
