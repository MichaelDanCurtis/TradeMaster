"""Local reference fixtures verify semantics, not provider/account entitlement."""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.research.test_alpaca_capture import Client, Response, Secrets, NOW
from tradingagents.research.data.alpaca_capture import CaptureLimits
from tradingagents.research.data.alpaca_reference import (
    ACTIONS_ENDPOINT, CALENDAR_ENDPOINT, ActionNormalizationPolicy, ReferenceRequest,
    calendar_session, capture_reference, normalize_references, read_reference_capture,
)
from tradingagents.research.data.contracts import DatasetBundle, SecurityMapping
from tradingagents.research.data.store import ArtifactIntegrityError, ArtifactStore


def calendar_request(**updates):
    return ReferenceRequest.model_validate({"kind": "calendar", "start": "2026-09-01", "end": "2026-09-10", **updates})


def action_request(**updates):
    return ReferenceRequest.model_validate({"kind": "corporate_actions", "start": "2026-09-01",
        "end": "2026-09-10", "symbols": ["AAA"], **updates})


def calendar_rows():
    return [{"date": f"2026-09-{day:02}", "open": "09:30", "close": "16:00"} for day in (1, 2, 3)]


def split(**updates):
    return {"id": "split-one", "symbol": "AAA", "ex_date": "2026-09-02", "process_date": "2026-09-03",
            "new_rate": 2, "old_rate": 1, "cusip": "fixture-only", **updates}


def dividend(**updates):
    return {"id": "dividend-one", "symbol": "AAA", "ex_date": "2026-09-03", "process_date": "2026-09-04",
            "rate": 1.25, "payable_date": "2026-09-09", "foreign": False, "special": False, **updates}


def mappings():
    return [SecurityMapping(instrument_id="issuer-aaa", symbol="AAA", valid_from="2020-01-01",
                            known_at="2020-01-01T00:00:00Z")]


def policy():
    return ActionNormalizationPolicy(actor="fixture-operator", rationale="Synthetic USD and conservative payment-time fixture",
        cash_currency="USD", payment_timing="end_of_payable_date_new_york")


def capture(store, request, *responses, **kwargs):
    client = Client(*responses)
    digest = capture_reference(request, store, secret_store=Secrets(), secret_ref="env:TEST_ONLY",
                               http_client=client, clock=lambda: NOW, **kwargs)
    return digest, read_reference_capture(store, digest), client


def source_pair(tmp_path, groups=None):
    store = ArtifactStore(tmp_path)
    cal, _, _ = capture(store, calendar_request(), Response(calendar_rows()))
    act, _, _ = capture(store, action_request(), Response({"corporate_actions": groups if groups is not None else {
        "forward_splits": [split()], "cash_dividends": [dividend()]}, "next_page_token": None}))
    return store, cal, act


def test_calendar_preserves_early_close_holidays_and_daylight_saving_offsets(tmp_path):
    rows = [{"date": "2026-03-06", "open": "09:30", "close": "16:00"},
            {"date": "2026-03-09", "open": "09:30", "close": "16:00"},
            {"date": "2026-11-27", "open": "09:30", "close": "13:00"}]
    store = ArtifactStore(tmp_path)
    digest, receipt, client = capture(store, calendar_request(start="2026-03-01", end="2026-11-30"), Response(rows))
    assert receipt.status == "complete" and receipt.unique_rows == 3
    assert client.calls[0][0] == CALENDAR_ENDPOINT
    assert client.calls[0][1]["params"]["date_type"] == "TRADING"
    sessions = [calendar_session(row) for row in rows]
    assert sessions[0].opens_at.astimezone(timezone.utc).hour == 14
    assert sessions[1].opens_at.astimezone(timezone.utc).hour == 13
    assert sessions[2].closes_at.astimezone(timezone.utc).hour == 18
    assert len(sessions) == 3  # No guessed weekdays, holidays or normal closing times.
    assert read_reference_capture(ArtifactStore(tmp_path), digest) == receipt


@pytest.mark.parametrize("rows,code", [
    ({"calendar": []}, "invalid_calendar_response"),
    ([{"date": "2026-09-01", "open": "9:30", "close": "16:00"}], "invalid_calendar_time"),
    ([{"date": "2026-09-01", "open": "16:00", "close": "09:30"}], "invalid_calendar_session"),
    ([{"date": "2026-09-11", "open": "09:30", "close": "16:00"}], "calendar_outside_request"),
    (list(reversed(calendar_rows())), "unordered_calendar"),
    ([calendar_rows()[0], {**calendar_rows()[0], "close": "13:00"}], "conflicting_calendar_revision"),
])
def test_calendar_errors_are_retained_without_substitution(tmp_path, rows, code):
    _, receipt, _ = capture(ArtifactStore(tmp_path), calendar_request(), Response(rows))
    assert receipt.failure_code == code and not receipt.pages[0].accepted


@pytest.mark.parametrize("day,opening", [("2026-03-08", "02:30"), ("2026-11-01", "01:30")])
def test_ambiguous_or_nonexistent_native_wall_clock_is_not_guessed(day, opening):
    with pytest.raises(ValueError, match="ambiguous_calendar_time"):
        calendar_session({"date": day, "open": opening, "close": "16:00"})


def test_actions_follow_pages_preserve_incomplete_unknown_types_and_use_process_dates(tmp_path):
    store = ArtifactStore(tmp_path)
    first = Response({"corporate_actions": {"forward_splits": [split(ex_date="2026-08-31")]},
                      "next_page_token": " opaque token "})
    second = Response({"corporate_actions": {"future_action_type": [{"id": "unknown", "symbol": "AAA"}]},
                       "next_page_token": None})
    _, receipt, client = capture(store, action_request(), first, second)
    assert receipt.status == "complete" and receipt.unique_rows == 2
    assert client.calls[0][0] == ACTIONS_ENDPOINT
    params = client.calls[0][1]["params"]
    assert params["data_quality"] == "all" and params["region"] == "us" and "types" not in params
    assert client.calls[1][1]["params"]["page_token"] == " opaque token "
    assert store.get(receipt.pages[1].response_artifact) == second.raw
    # The ex-date can precede the query. The query is filtered by processing date.
    assert json.loads(first.raw)["corporate_actions"]["forward_splits"][0]["ex_date"] == "2026-08-31"


def test_action_revision_across_pages_fails_and_same_version_is_idempotent(tmp_path):
    first = Response({"corporate_actions": {"forward_splits": [split()]}, "next_page_token": "next"})
    for name, last, status in (("same", split(), "complete"), ("revision", split(new_rate=3), "failed")):
        store = ArtifactStore(tmp_path / name)
        _, receipt, _ = capture(store, action_request(), first,
            Response({"corporate_actions": {"forward_splits": [last]}, "next_page_token": None}))
        assert receipt.status == status and receipt.unique_rows == 1
        if status == "complete":
            assert receipt.received_rows == 2
        else:
            assert receipt.failure_code == "conflicting_action_revision"


def test_normalization_keeps_ex_process_receipt_and_payment_times_distinct(tmp_path):
    store, calendar, actions = source_pair(tmp_path)
    digest = normalize_references(store, calendar, actions, mappings=mappings(), policy=policy())
    report = store.json(digest)
    assert report["issues"] == [] and not report["snapshot_ready"]
    normalized = {row["kind"]: row for row in report["actions"]}
    assert Decimal(normalized["split"]["split_ratio"]) == 2
    assert normalized["split"]["effective_session"] == "2026-09-02"
    assert datetime.fromisoformat(normalized["split"]["available_at"].replace("Z", "+00:00")) == NOW
    assert Decimal(normalized["dividend"]["cash_per_share_usd"]) == Decimal("1.25")
    assert normalized["dividend"]["payable_at"] == "2026-09-09T23:59:59.999999-04:00"
    assert report["declared_cash_policy"]["actor"] == "fixture-operator"
    assert report["action_lineage"][0]["process_date"] == "2026-09-03"
    assert len(report["calendar_lineage"]) == 3
    assert store.json(normalize_references(store, calendar, actions, mappings=mappings(), policy=policy())) == report


@pytest.mark.parametrize("category,row,reason", [
    ("stock_dividends", {"id": "stock", "symbol": "AAA"}, "unsupported_action_type"),
    ("cash_dividends", dividend(special=True), "nonordinary_or_unclassified_cash_dividend"),
    ("cash_dividends", dividend(foreign=None), "nonordinary_or_unclassified_cash_dividend"),
    ("cash_dividends", dividend(currency="EUR"), "dividend_currency_mismatch"),
    ("cash_dividends", dividend(payable_date="2026-09-01"), "payment_precedes_entitlement"),
    ("cash_dividends", dividend(payable_date=None), "invalid_reference_date"),
    ("cash_dividends", dividend(rate=-1), "invalid_dividend_rate"),
    ("forward_splits", split(old_rate=0), "invalid_split_ratio"),
    ("forward_splits", split(new_rate=0.5), "split_direction_mismatch"),
    ("forward_splits", split(process_date=None), "missing_process_date"),
    ("forward_splits", split(ex_date="2026-08-31"), "effective_session_missing"),
    ("forward_splits", split(symbol="BBB"), "unexpected_action_symbol"),
    ("forward_splits", split(due_bill_redemption_date="2026-09-04"), "due_bill_treatment_requires_review"),
    ("forward_splits", split(status="cancelled"), "unsupported_action_fields"),
    ("forward_splits", split(ex_date=1.25), "invalid_reference_date"),
])
def test_unresolved_actions_are_retained_in_review_and_never_silently_normalized(tmp_path, category, row, reason):
    store, calendar, actions = source_pair(tmp_path, {category: [row]})
    report = store.json(normalize_references(store, calendar, actions, mappings=mappings(), policy=policy()))
    assert report["actions"] == []
    assert report["issues"][0]["reasons"] == [reason]
    assert report["action_lineage"][0]["source_id"] == row["id"]


def test_missing_cash_interpretation_and_incompatible_mapping_require_review(tmp_path):
    store, calendar, actions = source_pair(tmp_path)
    report = store.json(normalize_references(store, calendar, actions, mappings=mappings()))
    assert len(report["actions"]) == 1
    assert report["issues"][0]["reasons"] == ["cash_currency_and_payment_policy_required"]
    for mapping_rows in ([], [mappings()[0], mappings()[0]],
                         [mappings()[0].model_copy(update={"known_at": NOW + timedelta(days=1)})]):
        report = store.json(normalize_references(store, calendar, actions, mappings=mapping_rows, policy=policy()))
        assert report["actions"] == []
        assert all(row["reasons"] == ["missing_or_ambiguous_instrument_mapping"] for row in report["issues"])


def test_reverse_split_preserves_new_over_old_ratio_and_empty_actions_make_no_coverage_claim(tmp_path):
    store, calendar, actions = source_pair(tmp_path / "reverse", {"reverse_splits": [split(new_rate=1, old_rate=10)]})
    report = store.json(normalize_references(store, calendar, actions, mappings=mappings()))
    assert Decimal(report["actions"][0]["split_ratio"]) == Decimal("0.1")
    store, calendar, actions = source_pair(tmp_path / "empty", {})
    report = store.json(normalize_references(store, calendar, actions, mappings=mappings()))
    assert report["actions"] == [] and not report["snapshot_ready"]
    assert any("Empty action results" in line for line in report["limitations"])


def test_partial_reference_or_wrong_kind_cannot_normalize_and_tampering_fails(tmp_path):
    store, calendar, actions = source_pair(tmp_path)
    partial, receipt, _ = capture(store, action_request(), Response({"corporate_actions": {}, "next_page_token": "next"}),
                                  limits=CaptureLimits(max_pages=1))
    with pytest.raises(ValueError, match="Partial"):
        normalize_references(store, calendar, partial, mappings=mappings())
    with pytest.raises(ValueError, match="calendar capture"):
        normalize_references(store, actions, calendar, mappings=mappings())
    good = read_reference_capture(store, actions)
    for updates in ({"unique_rows": 100}, {"endpoint": CALENDAR_ENDPOINT}, {"pages": []},
                    {"request_parameters": {**good.request_parameters, "data_quality": "complete"}}):
        with pytest.raises(ArtifactIntegrityError):
            read_reference_capture(store, store.put_json({**good.model_dump(mode="json"), **updates}))
    store.path(good.pages[0].response_artifact).write_bytes(b"changed")
    with pytest.raises(ArtifactIntegrityError):
        read_reference_capture(store, actions)


def test_reference_normalization_feeds_existing_total_return_kernel_without_backdating(tmp_path):
    from tests.research.conftest import spec_payload
    from tradingagents.research.contracts import StrategySpec
    from tradingagents.research.strategies.trend import trend_targets

    store, calendar, actions = source_pair(tmp_path)
    report = store.json(normalize_references(store, calendar, actions, mappings=mappings(), policy=policy()))
    def dataset(prices, actions):
        bars = [{"instrument_id": "issuer-aaa", "session": session["date"], "open": price, "high": price,
                 "low": price, "close": price, "volume": 1000, "available_at": NOW}
                for session, price in zip(report["sessions"], prices)]
        return DatasetBundle(timezone="America/New_York", sessions=report["sessions"],
            mappings=mappings(), bars=bars, actions=actions)
    original = dataset([100, 102, 104], [])
    adjusted = dataset([100, 51, Decimal("50.75")], report["actions"])
    payload = spec_payload()
    payload["universe"] = [{"instrument_id": "issuer-aaa", "symbol": "AAA", "risk_group": "equity"}]
    payload["rules"]["lookbacks_sessions"] = [2]
    payload["rules"]["volatility_sessions"] = 2
    spec = StrategySpec.model_validate(payload)
    expected = trend_targets(original, spec, NOW)
    actual = trend_targets(adjusted, spec, NOW)
    assert actual.status == "targets" and actual.signals == expected.signals
    assert actual.annualized_volatility == expected.annualized_volatility
    assert actual.portfolio_risk == expected.portfolio_risk
    assert trend_targets(adjusted, spec, NOW - timedelta(seconds=1)).status == "no_signal"


def test_offline_cli_normalization_and_restart(tmp_path):
    store, calendar, actions = source_pair(tmp_path / "artifacts")
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(json.dumps([row.model_dump(mode="json") for row in mappings()]))
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(policy().model_dump_json())
    command = [sys.executable, "-m", "tradingagents.research.data.alpaca_reference", "--artifacts", str(store.root)]
    result = subprocess.run([*command, "normalize", "--calendar", calendar, "--actions", actions,
        "--mappings", str(mapping_file), "--cash-policy", str(policy_file)], capture_output=True, text=True, check=True)
    output = json.loads(result.stdout)
    assert output["sessions"] == 3 and output["actions"] == 2 and output["issues"] == []
    assert store.json(output["normalization_hash"])["actions_capture"] == actions
    result = subprocess.run([*command, "inspect", calendar], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["kind"] == "calendar"


def test_reference_request_cannot_expand_to_arbitrary_markets_endpoints_or_coverage():
    for updates in ({"end": "2030-01-01"}, {"start": "1969-01-01"}, {"symbols": ["AAA"]}, {"kind": "orders"}):
        with pytest.raises(ValueError):
            calendar_request(**updates)
    for updates in ({"symbols": []}, {"symbols": ["AAA", "AAA"]}, {"types": ["forward_split"]}):
        with pytest.raises(ValueError):
            action_request(**updates)


def test_empty_calendar_does_not_produce_a_usable_normalization(tmp_path):
    store, _, actions = source_pair(tmp_path)
    calendar, receipt, _ = capture(store, calendar_request(), Response([]))
    assert receipt.status == "complete"
    report = store.json(normalize_references(store, calendar, actions, mappings=mappings(), policy=policy()))
    assert report["sessions"] == [] and report["actions"] == []
    assert report["issues"][0]["reasons"] == ["no_trading_sessions"]


def test_reference_http_transport_keeps_both_endpoints_read_only_and_preserves_denial(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.parse import parse_qs, urlsplit
    import requests

    calls = []
    deny_actions = [False]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            calls.append((self.command, parsed.path, parse_qs(parsed.query)))
            if parsed.path == "/v2/calendar":
                data = calendar_rows()
            else:
                if deny_actions[0]:
                    self.send_response(403)
                    self.end_headers()
                    return
                data = {"corporate_actions": {"forward_splits": [split()]}, "next_page_token": None}
            encoded = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class Transport:
        def get(self, url, **kwargs):
            assert url in {CALENDAR_ENDPOINT, ACTIONS_ENDPOINT}
            assert kwargs["allow_redirects"] is False
            return requests.get(f"http://127.0.0.1:{server.server_port}{urlsplit(url).path}", **kwargs)

    store = ArtifactStore(tmp_path)
    try:
        for request in (calendar_request(), action_request()):
            digest = capture_reference(request, store, secret_store=Secrets(), secret_ref="env:TEST_ONLY",
                http_client=Transport(), clock=lambda: NOW)
            assert read_reference_capture(store, digest).status == "complete"
        deny_actions[0] = True
        digest = capture_reference(action_request(), store, secret_store=Secrets(), secret_ref="env:TEST_ONLY",
            http_client=Transport(), clock=lambda: NOW)
        assert read_reference_capture(store, digest).failure_code == "http_403"
        assert len(calls) == 3 and all(call[0] == "GET" for call in calls)
        assert calls[0][2]["date_type"] == ["TRADING"]
        assert calls[1][2]["data_quality"] == ["all"] and "types" not in calls[1][2]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
