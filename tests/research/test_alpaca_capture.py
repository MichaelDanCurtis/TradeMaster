"""Native-shaped provider fixtures; these tests establish no real entitlement."""
import json
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from tradingagents.research.data.alpaca_capture import (
    ENDPOINT, CaptureLimits, DailyBarRequest, capture_daily_bars, read_capture,
)
from tradingagents.research.data.store import ArtifactIntegrityError, ArtifactStore


NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)


class Secrets:
    def get_secret(self, ref):
        assert ref == "env:TEST_ONLY"
        return '{"key_id":"test-only-key","secret_key":"never-persist-this-secret"}'


class Response:
    def __init__(self, payload, status=200):
        self.raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.status_code = status
        self.closed = False

    def iter_content(self, chunk_size):
        for start in range(0, len(self.raw), chunk_size):
            yield self.raw[start:start + chunk_size]

    def close(self):
        self.closed = True


class Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert len(self.calls) <= len(self.responses), "Unexpected retry or pagination call"
        response = self.responses[len(self.calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response


def bar(day="01", close=100.123456):
    return {"t": f"2026-09-{day}T04:00:00Z", "o": 100, "h": 102, "l": 99,
            "c": close, "v": 12345, "vw": 100.123456789, "n": 77}


def request():
    return DailyBarRequest(symbols=["BBB", "AAA"], start="2026-09-01T00:00:00Z",
                           end="2026-09-04T23:59:59Z", feed="sip")


def run(tmp_path, client, **kwargs):
    store = ArtifactStore(tmp_path)
    digest = capture_daily_bars(request(), store, secret_store=Secrets(), secret_ref="env:TEST_ONLY",
                               http_client=client, clock=lambda: NOW, **kwargs)
    return store, digest, read_capture(store, digest)


def test_all_symbol_pages_original_precision_and_restart_inspection(tmp_path):
    first = Response({"bars": {"AAA": [bar()]}, "next_page_token": "page-two"})
    second = Response({"bars": {"BBB": [bar("02")]}, "next_page_token": None})
    client = Client(first, second)
    store, digest, receipt = run(tmp_path, client)
    assert receipt.status == "complete"
    assert receipt.received_rows == receipt.unique_rows == 2
    assert receipt.missing_symbols == []
    assert receipt.entitlement_status == "not_verified" and not receipt.snapshot_ready
    assert len(client.calls) == 2 and first.closed and second.closed
    params = client.calls[0][1]["params"]
    assert receipt.request_parameters == params
    assert params["symbols"] == "AAA,BBB"
    assert {k: params[k] for k in ("feed", "adjustment", "asof", "currency", "sort", "timeframe")} == {
        "feed": "sip", "adjustment": "raw", "asof": "-", "currency": "USD", "sort": "asc", "timeframe": "1Day"}
    assert "page_token" not in params and client.calls[1][1]["params"]["page_token"] == "page-two"
    for url, call in client.calls:
        assert url == ENDPOINT and call["stream"] and call["allow_redirects"] is False
        assert 0 < call["timeout"] <= 15
    assert store.get(receipt.pages[0].response_artifact) == first.raw
    assert b"100.123456789" in first.raw
    assert all(p.requested_at <= p.received_at <= p.processed_at for p in receipt.pages)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert b"never-persist-this-secret" not in path.read_bytes()
    assert read_capture(ArtifactStore(tmp_path), digest) == receipt
    result = subprocess.run([sys.executable, "-m", "tradingagents.research.data.alpaca_capture",
        "--artifacts", str(tmp_path), "inspect", digest], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["unique_rows"] == 2
    assert "APCA" not in result.stdout


def test_short_empty_pages_still_follow_token_and_missing_symbol_is_explicit(tmp_path):
    client = Client(Response({"bars": {}, "next_page_token": " native opaque token "}),
                    Response({"bars": {"AAA": [bar()]}, "next_page_token": None}))
    _, _, receipt = run(tmp_path, client)
    assert receipt.status == "complete" and len(client.calls) == 2
    assert client.calls[1][1]["params"]["page_token"] == " native opaque token "
    assert receipt.pages[1].request_page_token == " native opaque token "
    assert receipt.missing_symbols == ["BBB"] and not receipt.snapshot_ready


def test_identical_overlap_is_counted_once_but_revision_is_never_selected_silently(tmp_path):
    first = {"bars": {"AAA": [bar()]}, "next_page_token": "next"}
    client = Client(Response(first), Response({"bars": {"AAA": [bar()]}, "next_page_token": None}))
    _, _, receipt = run(tmp_path / "duplicate", client)
    assert receipt.status == "complete" and receipt.received_rows == 2 and receipt.unique_rows == 1
    client = Client(Response(first), Response({"bars": {"AAA": [bar(close=101)]}, "next_page_token": None}))
    store, _, receipt = run(tmp_path / "revision", client)
    assert receipt.failure_code == "conflicting_bar_revision" and receipt.unique_rows == 1
    assert len(receipt.pages) == 2 and not receipt.pages[-1].accepted
    assert json.loads(store.get(receipt.pages[-1].response_artifact))["bars"]["AAA"][0]["c"] == 101


@pytest.mark.parametrize("payload,code", [
    ({"bars": {}}, "missing_page_fields"),
    ({"bars": {}, "next_page_token": ""}, "invalid_page_token"),
    ({"bars": {"FOREIGN": [bar()]}, "next_page_token": None}, "unexpected_symbols"),
    ({"bars": {"AAA": [{**bar(), "v": 1.5}]}, "next_page_token": None}, "invalid_bar_volume"),
    ({"bars": {"AAA": [{**bar(), "v": True}]}, "next_page_token": None}, "invalid_bar_volume"),
    ({"bars": {"AAA": [{**bar(), "c": True}]}, "next_page_token": None}, "invalid_bar_price"),
    ({"bars": {"AAA": [bar(close=103)]}, "next_page_token": None}, "invalid_bar_ohlc"),
    ({"bars": {"AAA": [bar("06")]}, "next_page_token": None}, "bar_outside_request"),
    ({"bars": {"AAA": [{**bar(), "t": "2026-09-01T04:00:00"}]}, "next_page_token": None}, "invalid_bar_timestamp"),
    ({"bars": {"AAA": [bar("02"), bar("01")]}, "next_page_token": None}, "unordered_bars"),
    (b'{"bars":{},"bars":{},"next_page_token":null}', "invalid_page_json"),
    (b'{"bars":{"AAA":[{"t":"2026-09-01T04:00:00Z","o":1,"h":2,"l":1,"c":NaN,"v":1}]},"next_page_token":null}', "invalid_bar_price"),
])
def test_malformed_success_is_retained_as_rejected_evidence(tmp_path, payload, code):
    response = Response(payload)
    store, _, receipt = run(tmp_path, Client(response))
    assert receipt.status == "failed" and receipt.failure_code == code
    assert receipt.received_rows == 0 and not receipt.pages[0].accepted
    assert store.get(receipt.pages[0].response_artifact) == response.raw


def test_pagination_cycles_and_cross_page_order_are_failures(tmp_path):
    client = Client(Response({"bars": {"AAA": [bar()]}, "next_page_token": "repeat"}),
                    Response({"bars": {"AAA": [bar("02")]}, "next_page_token": "repeat"}))
    _, _, receipt = run(tmp_path / "cycle", client)
    assert receipt.failure_code == "repeated_page_token" and len(client.calls) == 2
    client = Client(Response({"bars": {"BBB": [bar()]}, "next_page_token": "next"}),
                    Response({"bars": {"AAA": [bar("02")]}, "next_page_token": None}))
    _, _, receipt = run(tmp_path / "order", client)
    assert receipt.failure_code == "unordered_bars"


@pytest.mark.parametrize("limits,code,pages", [
    (CaptureLimits(max_pages=1), "page_limit", 1),
    (CaptureLimits(max_rows=1), "row_limit", 2),
    (CaptureLimits(max_page_bytes=2), "response_byte_limit", 0),
    (CaptureLimits(max_bytes=2), "response_byte_limit", 0),
])
def test_capacity_limits_never_publish_a_complete_capture(tmp_path, limits, code, pages):
    responses = [Response({"bars": {"AAA": [bar()]}, "next_page_token": "next"}),
                 Response({"bars": {"AAA": [bar("02")]}, "next_page_token": None})]
    _, _, receipt = run(tmp_path, Client(*responses), limits=limits)
    assert receipt.status == "failed" and receipt.failure_code == code
    assert len(receipt.pages) == pages


@pytest.mark.parametrize("status", [301, 302, 401, 403, 429, 500])
def test_provider_denial_has_no_retry_feed_fallback_or_error_body_capture(tmp_path, status):
    response = Response(b"never-persist-this-secret", status=status)
    client = Client(response)
    _, _, receipt = run(tmp_path, client)
    assert receipt.failure_code == f"http_{status}" and receipt.pages == []
    assert len(client.calls) == 1 and response.closed
    assert b"never-persist-this-secret" not in b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


def test_transport_failure_retains_completed_pages_and_sanitizes_exception(tmp_path):
    client = Client(Response({"bars": {"AAA": [bar()]}, "next_page_token": "next"}),
                    RuntimeError("never-persist-this-secret"))
    store, digest, receipt = run(tmp_path, client)
    assert receipt.status == "failed" and receipt.failure_code == "capture_unavailable"
    assert receipt.unique_rows == 1 and len(receipt.pages) == 1
    assert b"never-persist-this-secret" not in store.get(digest)


def test_cli_missing_credentials_saves_failure_without_network(tmp_path):
    import os

    path = tmp_path / "request.json"
    path.write_text(request().model_dump_json())
    env = dict(os.environ)
    env.pop("TRADEMASTER_CAPTURE_MISSING_TEST_SECRET", None)
    result = subprocess.run([sys.executable, "-m", "tradingagents.research.data.alpaca_capture",
        "--artifacts", str(tmp_path / "artifacts"), "capture", "--request", str(path),
        "--secret-ref", "env:TRADEMASTER_CAPTURE_MISSING_TEST_SECRET"],
        env=env, capture_output=True, text=True)
    assert result.returncode == 2 and result.stderr == ""
    output = json.loads(result.stdout)
    assert output["status"] == "failed" and output["failure_code"] == "credentials_unavailable"
    receipt = read_capture(ArtifactStore(tmp_path / "artifacts"), output["receipt_hash"])
    assert receipt.pages == [] and not receipt.snapshot_ready


def test_elapsed_limit_and_future_request_do_not_call_provider(tmp_path):
    ticks = iter([0, 61])
    client = Client()
    _, _, receipt = run(tmp_path, client, monotonic=lambda: next(ticks))
    assert receipt.failure_code == "elapsed_limit" and client.calls == []
    future = request().model_copy(update={"end": datetime(2026, 9, 6, tzinfo=timezone.utc)})
    with pytest.raises(ValueError, match="actual request time"):
        capture_daily_bars(future, ArtifactStore(tmp_path), secret_store=Secrets(), secret_ref="env:TEST_ONLY",
                           http_client=client, clock=lambda: NOW)
    assert client.calls == []


def test_receipt_and_native_page_tampering_are_detected(tmp_path):
    store, digest, receipt = run(tmp_path, Client(Response({"bars": {"AAA": [bar()]}, "next_page_token": None})))
    for updates in ({"unique_rows": 2}, {"missing_symbols": []}, {"status": "failed"},
                    {"pages": []}, {"observed_symbols": ["BBB"]},
                    {"request_parameters": {**receipt.request_parameters, "feed": "iex"}}):
        changed = {**receipt.model_dump(mode="json"), **updates}
        with pytest.raises(ArtifactIntegrityError):
            read_capture(store, store.put_json(changed))
    page = receipt.pages[0].model_dump(mode="json")
    for changes in ({"request_page_token": "foreign"}, {"accepted": False}, {"response_bytes": 1},
                    {"received_at": "2020-01-01T00:00:00Z"}):
        changed = {**receipt.model_dump(mode="json"), "pages": [{**page, **changes}]}
        with pytest.raises(ArtifactIntegrityError):
            read_capture(store, store.put_json(changed))
    store.path(receipt.pages[0].response_artifact).write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError):
        read_capture(store, digest)


def test_feed_and_aware_interval_are_required():
    payload = request().model_dump(mode="json")
    for updates in ({"feed": "unknown"}, {"symbols": ["AAA", "AAA"]}, {"symbols": ["../secrets"]},
                    {"start": "2026-09-01T00:00:00"}, {"end": payload["start"]}):
        with pytest.raises(ValueError):
            DailyBarRequest.model_validate({**payload, **updates})
    del payload["feed"]
    with pytest.raises(ValueError):
        DailyBarRequest.model_validate(payload)


def test_real_http_stream_pagination_redirect_and_read_only_transport(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.parse import parse_qs, urlsplit
    import requests

    calls = []
    mode = ["pages"]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            calls.append((self.command, parsed.path, query, self.headers.get("APCA-API-KEY-ID")))
            if mode[0] == "redirect":
                self.send_response(302)
                self.send_header("Location", "/must-not-be-called")
                self.end_headers()
                return
            symbol = "BBB" if "page_token" in query else "AAA"
            data = json.dumps({"bars": {symbol: [bar()]},
                               "next_page_token": None if symbol == "BBB" else "native-token"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class LocalFixtureTransport:
        def get(self, url, **kwargs):
            assert url == ENDPOINT
            return requests.get(f"http://127.0.0.1:{server.server_port}/v2/stocks/bars", **kwargs)

    try:
        _, _, receipt = run(tmp_path / "success", LocalFixtureTransport())
        assert receipt.status == "complete" and receipt.unique_rows == 2
        assert len(calls) == 2 and calls[1][2]["page_token"] == ["native-token"]
        assert all(method == "GET" and path == "/v2/stocks/bars" and key == "test-only-key"
                   for method, path, query, key in calls)
        assert all(query["feed"] == ["sip"] and query["asof"] == ["-"] for _, _, query, _ in calls)
        mode[0] = "redirect"
        _, _, receipt = run(tmp_path / "redirect", LocalFixtureTransport())
        assert receipt.failure_code == "http_302" and len(calls) == 3
        assert all(path != "/must-not-be-called" for _, path, _, _ in calls)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
