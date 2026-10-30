from copy import deepcopy
import pytest

from tradingagents.research.filing_stability import (
    conservative_public_time, document_url, earliest_entry, normalized_document,
    original_pairs, score_pair, submission_rows, validate_document,
)


def record(year=2024, **overrides):
    return {"cik": "0000000001", "form": "10-Q", "reportDate": f"{year}-03-31",
            "filingDate": f"{year}-05-01", "acceptanceDateTime": f"{year}-05-01T16:00:00Z",
            "accessionNumber": f"0000000001-{year % 100:02}-000001", "primaryDocument": "report.htm",
            "items": "", **overrides}


def doc(year=2024, **overrides):
    return {"dei": {"documenttype": ["10-Q"], "entitycentralindexkey": ["0000000001"],
                    "documentperiodenddate": [f"{year}-03-31"], "documentfiscalyearfocus": [str(year)],
                    "documentfiscalperiodfocus": ["Q1"]}, "characters_after": 20000,
            "distinct_tokens": 800, "tokens": ["alpha", "beta", "cash"], **overrides}


def test_remove_tables_hidden_xbrl_scripts_keep_visible_narrative():
    raw = b'''<html><body><ix:header><ix:nonnumeric name="dei:DocumentType">10-Q</ix:nonnumeric>
    secretcontext</ix:header><p>Visible revenue growth and cash.</p>
    <table><tr><td>tableonly<table><tr><td>nested</td></tr></table></td></tr></table>
    <div style="display: none">hiddenword</div><script>scriptword</script></body></html>'''
    result = normalized_document(raw)
    assert set(result["tokens"]) == {"visible", "revenue", "growth", "cash"}
    assert result["dei"]["documenttype"] == ["10-Q"]
    assert result == normalized_document(raw)


def test_unrelated_issuer_and_form_rejected():
    result = validate_document(doc(), record(cik="0000000002", form="10-K"))
    assert "missing_or_mismatched_issuer_cik" in result
    assert "missing_or_mismatched_documenttype" in result


def test_table_only_and_error_page_not_accepted():
    assert "insufficient_narrative_after_table_removal" in validate_document(
        normalized_document(b"<html>Access denied</html>"), record())


def test_inline_english_date_normalized_without_guessing_numeric_order():
    raw = '<html><ix:nonnumeric name="dei:DocumentPeriodEndDate">September\xa027 , 2025</ix:nonnumeric></html>'.encode()
    result = normalized_document(raw)
    assert result["dei"]["documentperiodenddate"] == ["2025-09-27"]
    assert result["dei_raw"]["documentperiodenddate"] != ["2025-09-27"]
    ambiguous = normalized_document(b'<p name="dei:DocumentPeriodEndDate">03/04/2024</p>')
    assert ambiguous["dei"]["documentperiodenddate"] == ["03/04/2024"]


def test_amendments_and_future_originals_do_not_replace_prior():
    rows = [record(), record(2023), record(2023, form="10-Q/A", accessionNumber="0000000001-24-000002")]
    pairs = original_pairs(rows)
    assert len(pairs) == 1 and pairs[0]["old"] == rows[1]
    assert not pairs[0]["metadata_issues"]
    bad = original_pairs([record(), record(2023, filingDate="2024-06-01")])
    assert "prior_document_not_previously_filed" in bad[0]["metadata_issues"]


def test_duplicate_originals_are_ambiguous_and_conflicting_accessions_fail():
    old = record(2023)
    alternate = record(2023, accessionNumber="0000000001-23-000002")
    assert "missing_or_ambiguous_prior_period" in original_pairs([record(), old, alternate])[0]["metadata_issues"]
    with pytest.raises(ValueError, match="Conflicting"):
        original_pairs([old, {**old, "primaryDocument": "different.htm"}])


def test_pair_requires_matching_fiscal_period_and_consecutive_years():
    pair = {"new": record(), "old": record(2023), "metadata_issues": []}
    new, old = doc(), doc(2023, tokens=["alpha", "cash", "debt"])
    result = score_pair(pair, new, old)
    assert result["jaccard"] == .5 and result["status"] == "structurally_validated"
    old["dei"]["documentfiscalperiodfocus"] = ["Q2"]
    assert score_pair(pair, new, old)["jaccard"] is None
    old["dei"]["documentfiscalperiodfocus"] = ["Q1"]
    old["dei"]["documentfiscalyearfocus"] = ["2022"]
    assert "fiscal_year_not_consecutive" in score_pair(pair, new, old)["issues"]


def test_retrieval_today_does_not_move_historical_timestamp():
    r = record()
    assert conservative_public_time(r).isoformat() == "2024-05-02T03:59:59+00:00"
    sessions = [{"open": f"2024-05-{d}T13:30:00Z", "close": f"2024-05-{d}T20:00:00Z"}
                for d in ["02", "03", "06", "07", "08", "09"]]
    assert earliest_entry(r, sessions) == "2024-05-06T13:30:00+00:00"
    assert earliest_entry(r, sessions, mode="forward", received_at="2024-05-06T15:00:00Z",
                          completed_at="2024-05-06T15:05:00Z") == "2024-05-09T13:30:00+00:00"
    with pytest.raises(ValueError, match="Forward"):
        earliest_entry(r, sessions, mode="forward")
    with pytest.raises(ValueError, match="Invalid exchange"):
        earliest_entry(r, sessions[::-1])


@pytest.mark.parametrize("name", ["../escape.htm", "/root.htm", "https://example.org/x", "a//b.htm", "a/./b.htm"])
def test_untrusted_metadata_cannot_redirect_document_capture(name):
    with pytest.raises(ValueError):
        document_url(record(primaryDocument=name))


def test_submissions_columns_must_align():
    with pytest.raises(ValueError, match="Misaligned"):
        submission_rows({"accessionNumber": ["a"], "form": []}, "1")
    assert submission_rows({"accessionNumber": ["a"], "form": ["10-Q"]}, "1")[0]["cik"] == "0000000001"


def test_fiscal_date_shift_beyond_tolerance_not_silently_paired():
    pairs = original_pairs([record(), record(2023, reportDate="2023-02-28")])
    assert pairs[0]["old"] is None
