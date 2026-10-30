from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from tradingagents.research.evidence.extraction import Completion
from tradingagents.research.evidence.provider import ProviderBinding
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.explorer_briefs import (
    BriefRequest, BriefService, ExplorerBriefRecord, collect_packet, validate_brief, now_utc,
)
from tradingagents.ui.market_data.base import MarketDataQuote

BINDING = ProviderBinding("codex-test", "codex-app-server", "test-model", None, "a"*64, None, False)
PACKET = {"sources": [{"source_id": "news_1", "text": "Company reports higher revenue."}], "gaps": ["Filings unread"]}


def output():
    claim = {"text": "A headline reports higher revenue; verify the filing.", "kind": "observation",
        "citations": [{"source_id": "news_1", "quote": "higher revenue"}]}
    return {"overview": claim, "catalysts": [claim], "bull_case": [], "bear_case": [],
        "rejection_tests": ["Would the filing contradict the headline?"], "gaps": ["What does the filing say?"]}


def completion(proposal=None, **kwargs):
    return Completion(text=json.dumps(proposal or output()), provider_id=BINDING.provider_id,
        model_id=BINDING.model_id, input_tokens=100, output_tokens=100, **kwargs)


def test_claims_require_exact_evidence_and_provider_identity():
    assert validate_brief(completion(), PACKET, BINDING)["proposal"]
    for citation in ({"source_id": "invented", "quote": "higher revenue"}, {"source_id": "news_1", "quote": "profits doubled"}):
        proposal = output()
        proposal["overview"]["citations"] = [citation]
        assert validate_brief(completion(proposal), PACKET, BINDING)["proposal"] is None
    assert validate_brief(completion(), PACKET, replace(BINDING, model_id="different"))["proposal"] is None
    assert validate_brief(completion(tool_calls=True), PACKET, BINDING)["proposal"] is None


def test_rejects_empty_citations_invalid_schema_and_excessive_quoting():
    proposal = output(); proposal["overview"]["citations"] = []
    assert validate_brief(completion(proposal), PACKET, BINDING)["proposal"] is None
    proposal = output(); quote = " ".join(["word"]*26)
    proposal["overview"]["citations"][0]["quote"] = quote
    packet = {"sources": [{"source_id": "news_1", "text": quote + " higher revenue"}]}
    assert validate_brief(completion(proposal), packet, BINDING)["proposal"] is None
    assert validate_brief(replace(completion(), text="not JSON"), PACKET, BINDING)["proposal"] is None


class QuoteProvider:
    def latest_quote(self, symbol, *, feed):
        return MarketDataQuote(symbol=symbol, timestamp=now_utc()-timedelta(days=2),
            bid_price=100, ask_price=101, bid_size=1, ask_size=1)


def news_item(**kwargs):
    return {"id": 1, "datetime": (now_utc()-timedelta(days=1)).timestamp(), "headline": "Company reports higher revenue.",
        "url": "https://example.com/news", "summary": "Read the report", "source": "Test publisher", **kwargs}


def test_packet_rejects_future_old_unsafe_and_duplicate_news():
    items = [news_item(datetime=(now_utc()+timedelta(days=1)).timestamp()),
        news_item(datetime=(now_utc()-timedelta(days=10)).timestamp()), news_item(url="javascript:alert(1)"),
        news_item(), news_item(), news_item(datetime=None)]
    packet = collect_packet("NVDA", lambda: (QuoteProvider(), {}), news_fetcher=lambda *a, **k: items)
    assert len(packet["sources"]) == 2
    assert packet["sources"][0]["published_at"] != packet["sources"][0]["retrieved_at"]
    assert packet["sources"][1]["url"] == "https://example.com/news"
    assert packet["gaps"]


def test_missing_connections_do_not_invent_evidence_or_leak_errors():
    def fail(*args, **kwargs):
        raise RuntimeError("secret-token")
    packet = collect_packet("NVDA", fail, news_fetcher=fail)
    assert not packet["sources"] and len(packet["gaps"]) == 3
    assert "secret-token" not in json.dumps(packet)


@pytest.fixture
def service(tmp_path, monkeypatch):
    _, sessions = create_session_factory(f"sqlite:///{tmp_path / 'briefs.db'}")
    init_db(sessions.kw["bind"])
    instance = BriefService(sessions, lambda: (QuoteProvider(), {}))
    monkeypatch.setattr(instance, "binding", lambda: BINDING)
    return instance


def request(key="request_identifier_0001", **kwargs):
    return BriefRequest(symbol="NVDA", idempotency_key=key, provider_config_hash="a"*64, **kwargs)


def test_durable_idempotency_and_single_active_request(service):
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: service.reserve(request()), range(2)))
    assert sum(fresh for _, fresh in results) == 1
    assert results[0][0].brief_id == results[1][0].brief_id
    with pytest.raises(ValueError, match="already running"):
        service.reserve(request("request_identifier_0002"))
    with pytest.raises(ValueError, match="different inputs"):
        service.reserve(request().model_copy(update={"symbol": "AAPL"}))
    recovered = BriefService(service.sessions, None)
    assert recovered.reserve(request())[1] is False


def test_expired_attempt_cannot_be_redispatched_or_overwritten(service):
    row, _ = service.reserve(request())
    with service.sessions() as session:
        saved = session.get(ExplorerBriefRecord, row.brief_id)
        saved.deadline_at = now_utc()-timedelta(seconds=1)
        session.add(saved); session.commit()
    assert service.history()[0].state == "unknown"
    assert not service.update(row.brief_id, state="completed")
    service.dispatch(row.brief_id)
    assert service.history()[0].state == "unknown"


def test_no_sources_means_no_model_call_and_retained_gaps(service, monkeypatch):
    monkeypatch.setattr("tradingagents.ui.explorer_briefs.collect_packet", lambda *args: {"sources": [], "gaps": ["Missing news"]})
    def forbidden(*args, **kwargs):
        pytest.fail("No process should be started without evidence")
    monkeypatch.setattr("tradingagents.ui.explorer_briefs.subprocess.Popen", forbidden)
    row, _ = service.reserve(request()); service.dispatch(row.brief_id)
    saved = service.history()[0]
    assert saved.state == "insufficient_evidence"
    assert saved.packet_hash and "Missing news" in saved.packet["gaps"]
    assert "No saved forward model forecast was available; briefing did not start one." in saved.packet['gaps']


def test_provider_change_before_dispatch_does_not_call_model(service, monkeypatch):
    row, _ = service.reserve(request())
    monkeypatch.setattr(service, "binding", lambda: replace(BINDING, config_hash="b"*64))
    monkeypatch.setattr("tradingagents.ui.explorer_briefs.collect_packet", lambda *args: PACKET)
    service.dispatch(row.brief_id)
    assert service.history()[0].state == "failed"


def test_completed_child_receipt_is_saved_and_dispatch_is_at_most_once(service, monkeypatch):
    calls = []
    monkeypatch.setattr("tradingagents.ui.explorer_briefs.collect_packet", lambda *args: PACKET)
    class Process:
        returncode = 0
        def __init__(self, args, **kwargs):
            self.output = args[-1]; calls.append(args)
        def communicate(self, envelope, *, timeout):
            from pathlib import Path
            payload = json.loads(envelope)
            assert "credential" not in payload
            Path(self.output).write_text(json.dumps(validate_brief(completion(), PACKET, BINDING)))
    monkeypatch.setattr("tradingagents.ui.explorer_briefs.subprocess.Popen", Process)
    monkeypatch.setattr("tradingagents.research.worker.stop_process", lambda process: None)
    row, _ = service.reserve(request()); service.dispatch(row.brief_id); service.dispatch(row.brief_id)
    saved = service.history()[0]
    assert len(calls) == 1 and saved.state == "completed"
    assert saved.receipt["proposal"] and saved.packet_hash


def test_unknown_child_outcome_is_not_automatically_retried(service, monkeypatch):
    attempts = []
    monkeypatch.setattr("tradingagents.ui.explorer_briefs.collect_packet", lambda *args: PACKET)
    def fail(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError("private provider diagnostic")
    monkeypatch.setattr("tradingagents.ui.explorer_briefs.subprocess.Popen", fail)
    row, _ = service.reserve(request()); service.dispatch(row.brief_id); service.dispatch(row.brief_id)
    saved = service.history()[0]
    assert saved.state == "unknown" and len(attempts) == 1
    assert "private provider diagnostic" not in saved.message
    assert service.reserve(request())[1] is False


def test_brief_api_preserves_idempotency_and_history(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from tradingagents.ui.api import create_app
    monkeypatch.setattr(BriefService, "binding", lambda self: BINDING)
    calls = []
    def dispatch(self, identifier):
        calls.append(identifier)
        self.update(identifier, state="insufficient_evidence", message="No model call made.")
    monkeypatch.setattr(BriefService, "dispatch", dispatch)
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'api.db'}"))
    status = client.get("/api/discover/briefs/status").json()
    assert status["available"] and status["model_id"] == BINDING.model_id
    payload = request().model_dump()
    first = client.post("/api/discover/briefs", json=payload)
    assert first.status_code == 202
    second = client.post("/api/discover/briefs", json=payload)
    assert second.json()["brief_id"] == first.json()["brief_id"] and len(calls) == 1
    history = client.get("/api/discover/briefs?symbol=NVDA").json()["briefs"]
    assert len(history) == 1 and history[0]["state"] == "insufficient_evidence"
    assert client.post("/api/discover/briefs", json={**payload, "symbol": "AAPL"}).status_code == 409
    assert client.post("/api/discover/briefs", json={**payload, "symbol": "../../secret"}).status_code == 422
    assert client.post("/api/discover/briefs", json={**payload, "idempotency_key": "request_identifier_0003", "provider_config_hash": "b"*64}).status_code == 409


def test_saved_company_evidence_and_filings_reach_the_bounded_model_packet(service,monkeypatch):
    from copy import deepcopy
    from tradingagents.ui.research_desk import Desk
    source={'profile':{'name':'NVIDIA'},'metrics':{},'financials':{},'sources':[], 'gaps':['Guidance not fully reviewed'],
        'collected_at':now_utc().isoformat(),'filing_excerpts':[{'form':'10-Q','filed':'2026-08-01','retrieved_at':now_utc().isoformat(),
            'url':'https://www.sec.gov/Archives/edgar/data/1/source.htm','text':'A preserved SEC excerpt.'}]}
    Desk(service.sessions).save('company','NVDA',source)
    monkeypatch.setattr('tradingagents.ui.explorer_briefs.collect_packet',lambda *args:deepcopy(PACKET))
    monkeypatch.setattr('tradingagents.ui.forecast_evidence.saved_forecast_source',lambda *args: (
        {'source_id':'forecast_lab','kind':'model_forecast','text':'Experimental output; future observations are pending.'},
        'Forecast outcomes are pending'))
    class Process:
        returncode=0
        def __init__(self,args,**kwargs):self.output=args[-1]
        def communicate(self,envelope,**kwargs):
            payload=json.loads(envelope);packet=payload['packet']
            assert {'company_facts','filing_0','forecast_lab'}<={s['source_id'] for s in packet['sources']}
            assert 'Forecast outcomes are pending' in packet['gaps']
            assert 'Guidance not fully reviewed' in packet['gaps']
            from pathlib import Path
            Path(self.output).write_text(json.dumps(validate_brief(completion(),packet,BINDING)))
    monkeypatch.setattr('tradingagents.ui.explorer_briefs.subprocess.Popen',Process)
    monkeypatch.setattr('tradingagents.research.worker.stop_process',lambda process:None)
    row,_=service.reserve(request());service.dispatch(row.brief_id)
    assert service.history()[0].state=='completed'


def test_child_preserves_sanitized_provider_failure_without_retry(tmp_path,monkeypatch):
    from dataclasses import asdict
    from io import BytesIO
    from types import SimpleNamespace
    from tradingagents.ui import explorer_brief_child as child
    monkeypatch.setattr(child.sys,'stdin',SimpleNamespace(buffer=BytesIO(json.dumps({'binding':asdict(BINDING),'packet':PACKET}).encode())))
    calls=[]
    def fail(*args,**kwargs):
        calls.append(True);raise RuntimeError('private provider diagnostic containing credentials')
    monkeypatch.setattr(child.ProviderExtractionClient,'complete',fail)
    path=tmp_path/'receipt.json';child.main(path)
    result=json.loads(path.read_text())
    assert len(calls)==1 and result['proposal'] is None and result['actual_model_id']=='unconfirmed'
    assert 'private' not in path.read_text() and result['dispatch_failure']
