import hashlib
import json

import httpx
import pytest

from scripts.research.capture_news_signals import ENDPOINT, capture

START = "2024-01-01T00:00:00Z"
END = "2024-01-03T00:00:00Z"
HEADERS = {"APCA-API-KEY-ID": "private-test-id", "APCA-API-SECRET-KEY": "private-test-secret"}


def run(tmp_path, handler, **kwargs):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return capture(tmp_path / "capture", ["AAPL", "BRK.B"], START, END, HEADERS,
                       client=client, **kwargs)


def test_complete_paginated_capture_preserves_versions_hashes_and_queries(tmp_path):
    calls = []
    article = {"id": 12, "created_at": START, "updated_at": END, "headline": "Example"}

    def handler(request):
        calls.append(request)
        assert str(request.url).startswith(ENDPOINT)
        assert request.headers["APCA-API-SECRET-KEY"] == HEADERS["APCA-API-SECRET-KEY"]
        assert request.url.params["limit"] == "50"
        assert request.url.params["include_content"] == "false"
        assert request.url.params["sort"] == "asc"
        return httpx.Response(200, json={"news": [article], "next_page_token": "next" if len(calls) == 1 else None})

    receipt = run(tmp_path, handler)
    assert receipt["status"] == "complete" and receipt["complete"]
    assert receipt["article_count"] == 2
    assert receipt["first_request_started_at"] <= receipt["last_retrieved_at"]
    assert calls[1].url.params["page_token"] == "next"
    for page in receipt["pages"]:
        raw = (tmp_path / "capture" / page["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == page["sha256"]
        assert json.loads(raw)["news"][0] == article
        assert page["request_started_at"] <= page["retrieved_at"]
    saved = (tmp_path / "capture" / "receipt.json").read_text()
    assert json.loads(saved) == receipt
    assert all(secret not in saved for secret in HEADERS.values())


def test_page_bound_is_truncated_not_complete(tmp_path):
    receipt = run(tmp_path, lambda _: httpx.Response(200, json={"news": [], "next_page_token": "next"}), max_pages=1)
    assert receipt["status"] == "truncated" and not receipt["complete"]
    assert receipt["failure"]["code"] == "max_pages"


def test_repeated_token_fails_instead_of_looping(tmp_path):
    receipt = run(tmp_path, lambda _: httpx.Response(200, json={"news": [], "next_page_token": "next"}))
    assert receipt["status"] == "failed"
    assert receipt["failure"]["code"] == "repeated_page_token"
    assert len(receipt["pages"]) == 2


def test_rate_limit_retries_bounded_and_no_error_body_saved(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr("scripts.research.capture_news_signals.time.sleep", sleeps.append)
    receipt = run(tmp_path, lambda _: httpx.Response(429, text=HEADERS["APCA-API-SECRET-KEY"]))
    assert len(receipt["attempts"]) == 3 and sleeps == [1, 2]
    assert receipt["failure"] == {"code": "http_error", "status_code": 429}
    assert receipt["pages"] == []
    assert HEADERS["APCA-API-SECRET-KEY"] not in (tmp_path / "capture" / "receipt.json").read_text()


def test_transport_exception_sanitized(tmp_path):
    def handler(request):
        raise httpx.ConnectError(HEADERS["APCA-API-SECRET-KEY"], request=request)
    receipt = run(tmp_path, handler)
    assert receipt["failure"]["code"] == "transport_error"
    assert HEADERS["APCA-API-SECRET-KEY"] not in (tmp_path / "capture" / "receipt.json").read_text()


def test_success_after_rate_limit_retains_attempt_audit(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.research.capture_news_signals.time.sleep", lambda _: None)
    replies = iter([httpx.Response(429), httpx.Response(200, json={"news": []})])
    receipt = run(tmp_path, lambda _: next(replies))
    assert receipt["complete"] and receipt["article_count"] == 0
    assert [a["status_code"] for a in receipt["attempts"]] == [429, 200]


def test_later_failure_preserves_captured_evidence(tmp_path):
    replies = iter([httpx.Response(200, json={"news": [{"id": 1}], "next_page_token": "next"}),
                    httpx.Response(403, text="not entitled")])
    receipt = run(tmp_path, lambda _: next(replies))
    assert not receipt["complete"] and receipt["status"] == "failed"
    assert receipt["article_count"] == 1 and len(receipt["pages"]) == 1
    page = receipt["pages"][0]
    assert hashlib.sha256((tmp_path / "capture" / page["file"]).read_bytes()).hexdigest() == page["sha256"]


@pytest.mark.parametrize("response,code", [
    (httpx.Response(302, headers={"location": "https://example.com"}), "http_error"),
    (httpx.Response(200, text="not json"), "invalid_json"),
    (httpx.Response(200, json={"news": "bad"}), "invalid_news_schema"),
    (httpx.Response(200, json={"news": [], "next_page_token": 3}), "invalid_page_token"),
])
def test_failed_receipt_for_bad_responses(tmp_path, response, code):
    receipt = run(tmp_path, lambda _: response)
    assert receipt["failure"]["code"] == code and not receipt["complete"]
    assert len(receipt["attempts"]) == 1


@pytest.mark.parametrize("symbols,start,end", [
    ([], START, END), (["AAPL"] * 101, START, END), (["AAPL", "AAPL"], START, END),
    (["https://example.com"], START, END), (["AAPL"], "2024-01-01", END),
    (["AAPL"], "2024-01-01T00:00:00", END), (["AAPL"], END, START),
])
def test_invalid_inputs_do_not_create_capture(tmp_path, symbols, start, end):
    with pytest.raises(ValueError):
        capture(tmp_path / "capture", symbols, start, end, HEADERS)
    assert not (tmp_path / "capture").exists()


def test_existing_root_never_overwritten(tmp_path):
    original = tmp_path / "keep.txt"
    original.write_text("preserved")
    with pytest.raises(FileExistsError):
        capture(tmp_path, ["AAPL"], START, END, HEADERS)
    assert original.read_text() == "preserved"
