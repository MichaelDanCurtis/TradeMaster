import json
from pathlib import Path

import httpx
import pytest

from scripts.research.event_research_pilot import Capture, check_protocol, freeze, parse_master


def test_frozen_selection_excludes_returns_and_detects_changed_source(tmp_path):
    symbols = [f"S{i:02}" for i in range(33)]
    source = tmp_path / "universe.json"
    data = {"issuers": {s: str(i + 1).zfill(10) for i, s in enumerate(symbols)},
            "sectors": {s: f"sector{i // 3}" for i, s in enumerate(symbols)}}
    source.write_text(json.dumps(data))
    root = tmp_path / "pilot"
    freeze(root, source)
    protocol = check_protocol(root)
    assert len(protocol["issuer_sample"]) == 25
    assert len({r["cik"] for r in protocol["issuer_sample"]}) == 25
    assert len({r["sector_descriptive_only"] for r in protocol["issuer_sample"]}) == 11
    with pytest.raises(FileExistsError):
        freeze(root, source)
    source.write_text(json.dumps({**data, "changed": True}))
    with pytest.raises(ValueError, match="source universe changed"):
        check_protocol(root)


def test_master_parser_ignores_headers_and_rejects_malformed_paths():
    raw = b'''CIK|Company Name|Form Type|Date Filed|Filename
1|Company|13F-HR|2024-01-02|edgar/data/1/0000000001-24-000001.txt
2|Other|SC TO-I|2024-01-03|../../private.txt
'''
    rows = parse_master(raw)
    assert len(rows) == 1 and rows[0]["cik"] == "0000000001"
    with pytest.raises(ValueError):
        parse_master(b"<html>denied</html>")


def test_capture_records_exact_bytes_caches_and_detects_tampering(tmp_path):
    (tmp_path / "raw").mkdir()
    config = {"headers": {"User-Agent": "test"}, "minimum_request_spacing_seconds": 0,
              "max_attempts": 1}
    calls = []
    def respond(request):
        calls.append(request.url)
        return httpx.Response(200, content=b'{"original": true}', headers={"Content-Type": "application/json"})
    c = Capture(tmp_path, config)
    c.client.close(); c.client = httpx.Client(transport=httpx.MockTransport(respond))
    url = "https://data.sec.gov/submissions/CIK0000000001.json"
    assert c.get(url) == c.get(url) == b'{"original": true}'
    assert len(calls) == 1
    r = next(iter(c.receipt.values()))
    assert r["status"] == "captured" and r["requested_at"] <= r["retrieved_at"]
    (tmp_path / r["file"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="source changed"):
        c.get(url)
    with pytest.raises(ValueError, match="official public SEC"):
        c.get("https://example.com/data")
    c.close()


def test_capture_does_not_follow_redirect_or_parse_http_failure(tmp_path):
    (tmp_path / "raw").mkdir()
    c = Capture(tmp_path, {"headers": {}, "minimum_request_spacing_seconds": 0, "max_attempts": 1})
    c.client.close()
    c.client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"Location": "https://other.example/a"})))
    assert c.get("https://www.sec.gov/Archives/example.txt") is None
    assert next(iter(c.receipt.values()))["http_status"] == 302
    assert not list((tmp_path / "raw").iterdir())
    c.close()
