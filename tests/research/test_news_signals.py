"""Causal and evidence-boundary checks for offline news feature snapshots."""
from copy import deepcopy

import pytest

from tradingagents.research.news_signals import (
    available_at,
    agent_snapshot,
    deduplicate,
    normalize_article,
    normalize_web_excerpt,
    snapshot,
    validate_agent_evidence,
    validate_tone,
)


def article(*, identifier="1", headline="Apple raises earnings guidance", symbols=None,
            published="2026-09-01T10:00:00Z", updated=None, received=None, url=None):
    return normalize_article({
        "id": identifier, "headline": headline, "symbols": symbols or ["AAPL"],
        "created_at": published, "updated_at": updated or published,
        "url": url or f"https://news.example/articles/{identifier}", "source": "Example",
    }, received or updated or published, "a" * 64)


def tone(row, *, completed="2026-09-01T10:01:00Z", probabilities=None):
    return {"version_id": row["version_id"], "completed_at": completed,
            "probabilities": probabilities or {"positive": .8, "negative": .1, "neutral": .1},
            "model": "test/local-tone", "revision": "b" * 40}


def evidence(row):
    return {"version_id": row["version_id"], "symbol": "AAPL",
            "event_type": "earnings_guidance", "direction": "positive", "relevance": "direct",
            "passages": [{"start": 0, "end": len(row["headline"]), "quote": row["headline"]}],
            "completed_at": "2026-09-01T10:01:00Z", "extractor": "test-agent",
            "prompt_sha256": "c" * 64}


def test_swapped_numeric_meanings_are_not_duplicates():
    first = article(headline="Apple revenue 10 billion profit 20 billion")
    second = article(identifier="2", headline="Apple revenue 20 billion profit 10 billion")
    assert len(deduplicate([first, second])) == 2


def test_changed_meaning_at_same_url_is_not_a_duplicate():
    first = article(headline="Apple raises earnings guidance")
    second = article(identifier="2", headline="Apple cuts earnings guidance", url=first["url"])
    assert len(deduplicate([first, second])) == 2


def test_agent_labels_are_observed_only_and_unknown_is_missing():
    row = article()
    label = evidence(row)
    label["direction"] = "unknown"
    result = agent_snapshot([row], [label], "AAPL", "2026-09-01T10:16:00Z")
    assert result["collected_evidence_count"] == 0
    result = agent_snapshot([row], [label], "AAPL", "2026-09-01T10:17:00Z")
    assert result["collected_evidence_count"] == 1
    assert result["mean_direction_label"] is None
    assert result["direction_counts"]["unknown"] == 1


def test_repeated_agent_labels_do_not_inflate_evidence():
    row = article()
    label = evidence(row)
    result = agent_snapshot([row], [label, label], "AAPL", "2026-09-02T00:00:00Z")
    assert result["collected_evidence_count"] == 1
    assert result["mean_direction_label"] == 1
    changed = {**label, "direction": "negative"}
    with pytest.raises(ValueError, match="Conflicting"):
        agent_snapshot([row], [label, changed], "AAPL", "2026-09-02T00:00:00Z")


def snap(rows, tones=None, cutoff="2026-09-02T00:00:00Z", **kwargs):
    return snapshot(rows, tones or {}, "AAPL", cutoff, **kwargs)


def test_future_article_revision_and_receipt_cannot_change_past_snapshot():
    old = article()
    original_tone = tone(old)
    baseline = snap([old], {old["version_id"]: original_tone})
    future_publication = article(identifier="2", published="2026-09-03T10:00:00Z")
    future_revision = article(headline="Apple cuts earnings guidance", updated="2026-09-03T10:00:00Z")
    future_receipt = article(identifier="3", received="2026-09-03T10:00:00Z")
    assert snap([future_revision, old, future_receipt, future_publication],
                {old["version_id"]: original_tone}) == baseline


def test_revision_replaces_original_only_after_revision_is_available():
    old = article()
    revised = article(headline="Apple cuts earnings guidance", updated="2026-09-02T10:00:00Z")
    assert snap([old, revised])["version_ids"] == [old["version_id"]]
    after = snap([old, revised], cutoff="2026-09-02T10:16:00Z")
    assert after["version_ids"] == [revised["version_id"]]
    assert after["article_count"] == 1


def test_future_inference_does_not_score_an_available_article():
    row = article()
    delayed = tone(row, completed="2026-09-03T10:00:00Z")
    result = snap([row], {row["version_id"]: delayed})
    assert result["article_count"] == 1
    assert result["scored_single_ticker_count"] == 0
    assert result["mean_headline_tone"] is None


def test_exact_availability_cutoff_is_excluded_and_next_second_admitted():
    row = article()
    assert snap([row], cutoff="2026-09-01T10:15:00Z")["article_count"] == 0
    assert snap([row], cutoff="2026-09-01T10:15:01Z")["article_count"] == 1
    classified = tone(row)
    assert snap([row], {row["version_id"]: classified}, cutoff="2026-09-01T10:16:00Z")["scored_single_ticker_count"] == 0
    assert snap([row], {row["version_id"]: classified}, cutoff="2026-09-01T10:16:01Z")["scored_single_ticker_count"] == 1


def test_timezone_equivalence_and_window_lower_boundary():
    row = article(published="2026-09-01T03:00:00-07:00")
    assert row["published_at"] == "2026-09-01T10:00:00+00:00"
    assert snap([row], cutoff="2026-09-08T10:15:00Z")["article_count"] == 1
    assert snap([row], cutoff="2026-09-08T10:15:01Z")["article_count"] == 0


def test_observed_and_retrospective_proxy_availability_remain_distinct():
    row = article(received="2026-09-03T10:00:00Z")
    assert snap([row])["article_count"] == 0
    proxy = snap([row], mode="retrospective_proxy")
    assert proxy["article_count"] == 1
    assert proxy["mode"] == "retrospective_proxy"
    assert proxy["qualified_for_return_claim"] is False


@pytest.mark.parametrize("field,value", [
    ("created_at", None), ("updated_at", None), ("created_at", "2026-09-01"),
    ("created_at", "2026-09-01T10:00:00"), ("updated_at", "2026-08-31T10:00:00Z"),
    ("updated_at", "2026-09-04T10:00:00Z"),
])
def test_missing_naive_or_inconsistent_article_stamps_rejected(field, value):
    raw = {"id": "1", "headline": "Apple report", "symbols": ["AAPL"],
           "created_at": "2026-09-01T10:00:00Z", "updated_at": "2026-09-01T10:00:00Z",
           "url": "https://news.example/1", "source": "Example"}
    raw[field] = value
    with pytest.raises(ValueError):
        normalize_article(raw, "2026-09-03T10:00:00Z", "a" * 64)


@pytest.mark.parametrize("probabilities", [
    {}, {"positive": .8, "negative": .2},
    {"positive": float("nan"), "negative": .1, "neutral": .1},
    {"positive": float("inf"), "negative": .1, "neutral": .1},
    {"positive": True, "negative": 0, "neutral": 0},
    {"positive": -.1, "negative": .1, "neutral": 1},
    {"positive": .9, "negative": .9, "neutral": .1},
])
def test_missing_nonfinite_or_invalid_probabilities_rejected(probabilities):
    row = article()
    result = tone(row)
    result["probabilities"] = probabilities
    with pytest.raises(ValueError):
        validate_tone(result, row)


@pytest.mark.parametrize("field,value", [
    ("version_id", "wrong-version"), ("completed_at", "2026-09-01T09:59:00Z"),
    ("completed_at", None), ("revision", "main"), ("model", ""),
])
def test_tone_requires_captured_version_and_pinned_inference_provenance(field, value):
    row = article()
    result = tone(row)
    result[field] = value
    with pytest.raises(ValueError):
        validate_tone(result, row)


def test_empty_coverage_is_distinct_from_classified_neutral_text():
    empty = snap([], coverage_complete=True)
    row = article()
    neutral = tone(row, probabilities={"positive": .1, "negative": .1, "neutral": .8})
    populated = snap([row], {row["version_id"]: neutral}, coverage_complete=True)
    assert empty["coverage"] == populated["coverage"] == "endpoint_complete"
    assert empty["mean_headline_tone"] is None
    assert empty["neutral_count"] == 0
    assert populated["mean_headline_tone"] == 0
    assert populated["neutral_count"] == 1
    assert snap([])["coverage"] == "incomplete"


def test_multi_ticker_document_tone_abstains_without_issuer_interpretation():
    row = article(symbols=["AAPL", "MSFT"])
    result = snap([row], {row["version_id"]: tone(row)})
    assert result["article_count"] == 1
    assert result["unscored_count"] == 1
    assert result["mean_headline_tone"] is None


def test_duplicates_do_not_inflate_tone_or_source_diversity():
    first = article()
    second = article(identifier="2", published="2026-09-01T10:02:00Z")
    result = snap([second, first], {first["version_id"]: tone(first),
                                  second["version_id"]: tone(second, completed="2026-09-01T10:03:00Z")})
    assert result["article_count"] == 2
    assert result["headline_cluster_count"] == 1
    assert result["duplicates_removed"] == 1
    assert result["scored_single_ticker_count"] == 1
    assert result["distribution_family_count"] == 1


def test_future_duplicate_is_filtered_before_clustering():
    first = article(identifier="2")
    future_copy = article(identifier="1", published="2026-09-01T09:00:00Z",
                          received="2026-09-03T10:00:00Z")
    baseline = snap([first], {first["version_id"]: tone(first)})
    assert snap([future_copy, first], {first["version_id"]: tone(first)}) == baseline


def test_number_and_negation_changes_are_not_near_duplicate_collapsed():
    rows = [article(identifier="1", headline="Apple revenue guidance is 10 billion for next quarter"),
            article(identifier="2", headline="Apple revenue guidance is 20 billion for next quarter"),
            article(identifier="3", headline="Apple revenue guidance is not 10 billion for next quarter")]
    assert len(deduplicate(rows)) == 3


def test_valid_agent_evidence_and_opposite_multi_issuer_labels_are_accepted():
    row = article(headline="Apple gains contract as Microsoft loses contract", symbols=["AAPL", "MSFT"])
    first = evidence(row)
    assert validate_agent_evidence(first, row) == first
    second = deepcopy(first)
    second.update(symbol="MSFT", direction="negative")
    assert validate_agent_evidence(second, row) == second


@pytest.mark.parametrize("mutation", ["quote", "bounds", "boolean_offset", "order", "passage_order", "issuer", "no_passages"])
def test_agent_unsupported_spans_and_unexpected_order_fields_rejected(mutation):
    row = article()
    result = evidence(row)
    if mutation == "quote": result["passages"][0]["quote"] = "Apple cuts guidance"
    elif mutation == "bounds": result["passages"][0]["end"] += 1
    elif mutation == "boolean_offset": result["passages"][0]["start"] = False
    elif mutation == "order": result["order"] = {"side": "buy", "quantity": 100}
    elif mutation == "passage_order": result["passages"][0]["order"] = "buy"
    elif mutation == "issuer": result["symbol"] = "MSFT"
    elif mutation == "no_passages": result["passages"] = []
    with pytest.raises(ValueError):
        validate_agent_evidence(result, row)


@pytest.mark.parametrize("latency", [-1, float("nan"), float("inf")])
def test_invalid_latency_rejected(latency):
    with pytest.raises(ValueError):
        available_at(article(), "observed", latency_minutes=latency)


def web_excerpt(**overrides):
    values = {"url": "https://issuer.example/news/release", "symbol": "AAPL",
              "excerpt": "Apple announces a new manufacturing facility.",
              "publication_date": "2026-08-13", "retrieved_at": "2026-09-07T20:00:00Z",
              "source_sha256": "d" * 64}
    values.update(overrides)
    return normalize_web_excerpt(**values)


def test_web_excerpt_preserves_day_precision_and_observed_provenance():
    row = web_excerpt()
    assert row["publication_date"] == "2026-08-13"
    assert row["publication_precision"] == "day"
    assert row["published_at"] == "2026-08-14T00:00:00+00:00"
    assert row["retrieved_at"] == row["updated_at"] == "2026-09-07T20:00:00+00:00"
    assert row["allowed_modes"] == ["observed"]
    assert row["text_scope"] == "captured_excerpt"
    assert row["issuer_identity"] == "agent_selected_requires_review"
    assert available_at(row, "observed").isoformat() == "2026-09-07T20:15:00+00:00"


def test_old_dated_web_page_cannot_be_backdated_into_proxy_or_past_snapshot():
    row = web_excerpt()
    with pytest.raises(ValueError, match="cannot be backdated"):
        available_at(row, "retrospective_proxy")
    with pytest.raises(ValueError, match="cannot be backdated"):
        snap([row], mode="retrospective_proxy", cutoff="2026-08-20T00:00:00Z")
    assert snap([row], cutoff="2026-09-07T20:15:00Z")["article_count"] == 0
    assert snap([row], cutoff="2026-09-07T20:15:01Z")["article_count"] == 1


def test_same_day_web_publication_uses_explicit_next_utc_day_convention():
    row = web_excerpt(publication_date="2026-09-07")
    assert row["publication_precision"] == "day"
    assert available_at(row, "observed").isoformat() == "2026-09-08T00:15:00+00:00"
    assert snap([row], cutoff="2026-09-08T00:15:00Z")["article_count"] == 0


def test_later_web_capture_cannot_rewrite_prior_snapshot():
    old = web_excerpt()
    revised = web_excerpt(excerpt="Apple postpones the manufacturing facility.",
                          retrieved_at="2026-09-08T20:00:00Z", source_sha256="e" * 64)
    cutoff = "2026-09-07T21:00:00Z"
    assert snap([old, revised], cutoff=cutoff) == snap([old], cutoff=cutoff)
    assert snap([old, revised], cutoff="2026-09-08T21:00:00Z")["version_ids"] == [revised["version_id"]]


@pytest.mark.parametrize("field,value", [
    ("publication_date", "2026-09-08"), ("publication_date", "2026-08-13T10:00:00Z"),
    ("publication_date", "2026-02-30"), ("retrieved_at", "2026-09-07T20:00:00"),
    ("source_sha256", "unhashed"), ("symbol", "aapl"), ("excerpt", ""),
    ("url", "http://issuer.example/news"), ("url", "https://user:password@issuer.example/news"),
])
def test_invalid_web_dates_identity_and_provenance_rejected(field, value):
    with pytest.raises(ValueError):
        web_excerpt(**{field: value})
