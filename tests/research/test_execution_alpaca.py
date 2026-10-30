"""Actual requests HTTP transport against a bounded local Alpaca protocol fixture."""
import json
from contextlib import contextmanager
from decimal import Decimal as D
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit, parse_qs

import pytest
import requests
from sqlmodel import select

from tradingagents.research.execution_repository import PaperExecutionRepository
from tradingagents.research.repository import ConflictError
from tradingagents.ui.brokers.alpaca import AlpacaPaperBroker
from tradingagents.ui.brokers.service import BrokerService
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.models import BrokerOrderRecord
from tradingagents.ui.secrets import EnvSecretStore


@contextmanager
def paper_server():
    state = {"orders": {}, "posts": [], "deletes": [], "families":{}, "family_reads":[], "lose_ack": False, "ack_cancel": True, "change_cash": False, "account_reads": 0}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def reply(self, body, code=200):
            raw = json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            url = urlsplit(self.path)
            orders = list(state["orders"].values())
            if url.path == "/v2/account":
                state["account_reads"] += 1
                cash = "900" if state["change_cash"] and state["account_reads"] % 2 == 0 else "1000"
                committed = sum((D(o["qty"])*D(o["limit_price"]) for o in orders if o["status"] not in {"canceled", "filled"}), D(0))
                self.reply({"id": "fixture-account", "currency": "USD", "equity": cash, "cash": cash, "buying_power": str(D(cash)-committed), "trading_blocked": False, "account_blocked": False, "status": "ACTIVE"})
            elif url.path == "/v2/positions": self.reply([])
            elif url.path == "/v2/orders": self.reply([o for o in orders if o["status"] not in {"canceled", "filled"}])
            elif url.path in {"/v2/account/activities/FILL", "/v2/account/activities"}: self.reply([])
            elif url.path == "/v2/orders:by_client_order_id":
                order = state["orders"].get(parse_qs(url.query)["client_order_id"][0])
                self.reply(order or {}, 200 if order else 404)
            elif url.path.startswith("/v2/orders/"):
                state["family_reads"].append(parse_qs(url.query))
                family = state["families"].get(url.path.removeprefix("/v2/orders/"))
                self.reply(family or {},200 if family else 404)
            else: self.reply({}, 404)
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["posts"].append(body)
            client_id = body["client_order_id"]
            if client_id in state["orders"]: return self.reply({}, 422)
            order = {**body, "id": "d0a673fb-b018-4c28-b04e-a71756375e16", "status": "accepted", "filled_qty": "0", "filled_avg_price": None}
            state["orders"][client_id] = order
            if state["lose_ack"]:
                self.close_connection = True
                return
            self.reply(order)
        def do_DELETE(self):
            state["deletes"].append(self.path)
            if state["ack_cancel"]:
                for order in state["orders"].values(): order["status"] = "canceled"
            self.reply({}, 202)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{server.server_port}", state
    finally: server.shutdown(); server.server_close(); thread.join(timeout=2)


@pytest.fixture
def wire(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_WIRE_FIXTURE", '{"key_id":"fixture-key","secret_key":"fixture-secret"}')
    with paper_server() as (url, state), requests.Session() as http:
        broker = AlpacaPaperBroker(secret_store=EnvSecretStore(), secret_ref="env:PAPER_WIRE_FIXTURE", price_estimator=lambda _:100, http_client=http, base_url=url, drawdown_observer=lambda *_:D(0))
        engine, sessions = create_session_factory(f"sqlite:///{tmp_path/'wire.db'}"); init_db(engine)
        repo = UiRepository(sessions)
        run = repo.create_run(RunConfig(ticker="AAA", trade_date="2026-04-30", broker_mode="paper"))
        yield BrokerService(repo, broker), broker, repo, state, run.run_id, sessions


def preview(wire):
    service, _, _, _, run_id, _ = wire
    result = service.preview_order(run_id, "AAA", "buy", 650)
    service.approve_order(result.intent_id, "operator", result.order_hash)
    return result


def test_wire_uses_exact_limit_quantity_and_never_a_fresh_quote(wire):
    service, broker, _, state, _, _ = wire
    result = preview(wire)
    broker._price_estimator = lambda _: (_ for _ in ()).throw(AssertionError("submission must not reprice"))
    order = service.submit_approved_order(result.intent_id)
    assert order.status == "accepted" and result.evidence_kind == "fixture"
    assert state["posts"] == [{"client_order_id": result.intent_id, "symbol":"AAA", "side":"buy", "qty":"6", "type":"limit", "limit_price":"100.00", "time_in_force":"day"}]


def test_wire_reads_completed_parent_nested_children_and_rejects_foreign_child(wire):
    _, broker, _, state, _, _ = wire
    parent={"id":"parent","client_order_id":"parent-client","symbol":"AAA","side":"buy","qty":"2","filled_qty":"2",
        "filled_avg_price":"100","status":"filled","order_class":"bracket"}
    stop={**parent,"id":"stop","client_order_id":"stop-client","side":"sell","type":"stop","stop_price":"90",
        "filled_qty":"0","filled_avg_price":None,"status":"canceled"}
    profit={**parent,"id":"profit","client_order_id":"profit-client","side":"sell","type":"limit","limit_price":"110","filled_avg_price":"110"}
    state["families"]["parent"]={**parent,"legs":[stop,profit]}
    family=broker.order_family("parent")
    assert family.parent.status=="filled" and family.children[1].observation.broker_order_id=="profit"
    assert state["family_reads"]==[{"nested":["true"]}] and not state["posts"] and not state["deletes"]
    state["families"]["parent"]["legs"][0]["symbol"]="BBB"
    with pytest.raises(ValueError,match="parent's long position"): broker.order_family("parent")


def test_wire_lost_http_response_then_restart_reconciles_one_economic_order(wire):
    service, broker, repo, state, _, sessions = wire
    result = preview(wire); state["lose_ack"] = True
    assert service.submit_approved_order(result.intent_id).status == "unknown"
    # Fresh service/repository represent an application restart; the broker's
    # independent state survives the lost HTTP response.
    restarted = BrokerService(UiRepository(sessions), broker)
    for _ in range(3): assert restarted.submit_approved_order(result.intent_id).status == "accepted"
    assert len(state["orders"]) == len(state["posts"]) == 1
    with sessions() as session:
        assert len(session.exec(select(BrokerOrderRecord)).all()) == 1


def test_wire_cancel_http_ack_does_not_confirm_cancellation(wire):
    service, _, _, state, _, sessions = wire
    result = preview(wire); service.submit_approved_order(result.intent_id)
    state["ack_cancel"] = False
    assert service.cancel_order(result.intent_id, "operator") == "pending_cancel"
    boundary = PaperExecutionRepository(sessions)
    record = boundary.for_intent(result.intent_id)
    assert boundary.attempt_for_order(record.order_id).state == "accepted"
    state["ack_cancel"] = True
    assert service.cancel_order(result.intent_id, "operator") == "canceled"
    assert len(state["orders"]) == len(state["posts"]) == 1


def test_wire_missing_drawdown_is_unknown_and_blocks_new_entry(wire):
    service, broker, _, state, run_id, _ = wire
    broker._drawdown_observer = None
    snapshot = broker.paper_snapshot()
    assert snapshot.drawdown_fraction is None
    with pytest.raises(ConflictError, match="drawdown is unavailable"):
        service.preview_order(run_id, "AAA", "buy", 600)
    assert not state["posts"]


def test_wire_account_change_during_snapshot_cannot_create_intent(wire):
    service, _, repo, state, run_id, _ = wire
    state["change_cash"] = True
    with pytest.raises(ValueError, match="changed during observation"):
        service.preview_order(run_id, "AAA", "buy", 600)
    assert not state["posts"]


@pytest.mark.parametrize("url", ["https://api.alpaca.markets", "https://paper-api.alpaca.markets.evil.test", "http://paper-api.alpaca.markets", "https://user@paper-api.alpaca.markets", "https://paper-api.alpaca.markets?redirect=live"])
def test_real_transport_cannot_use_an_unverified_or_live_host(url):
    with pytest.raises(ValueError, match="official Alpaca paper endpoint"):
        AlpacaPaperBroker(secret_store=EnvSecretStore(), secret_ref="env:UNREAD", price_estimator=lambda _:100, base_url=url)


def test_account_worker_recovers_lost_ack_without_reposting_and_records_equity(wire):
    from tradingagents.research.accounting_repository import PaperAccountingRepository
    from tradingagents.research.accounting_service import ReconciledPaperBroker
    from tradingagents.research.accounting_worker import reconcile_configured_account
    _,broker,repo,state,run_id,sessions=wire
    accounting=PaperAccountingRepository(sessions)
    baseline=accounting.preview_baseline(broker.paper_snapshot())
    accounting.approve_baseline(baseline.baseline_id,baseline.content_hash,"operator")
    service=BrokerService(repo,ReconciledPaperBroker(broker,accounting))
    result=service.preview_order(run_id,"AAA","buy",650)
    service.approve_order(result.intent_id,"operator",result.order_hash)
    state["lose_ack"]=True
    assert service.submit_approved_order(result.intent_id).status=="unknown"
    outcome=reconcile_configured_account(sessions,broker)
    assert outcome["status"]=="reconciled" and outcome["drawdown_available"]
    assert accounting.list_accounts()[0]["latest"].report["outstanding_execution"][0]["state"]=="accepted"
    assert len(state["orders"])==len(state["posts"])==1


def snapshot_marks(wire, monkeypatch, marks, *, cash_changes=False):
    """Independently timed account/position GETs, stable shares and cash."""
    import copy
    _, broker, _, state, _, _ = wire
    calls=[]
    def read_state():
        index=len(calls);calls.append(index)
        cash='901' if cash_changes and index>=2 else '900'
        return ({'id':'fixture-account','currency':'USD','cash':cash,'equity':'1000',
                 'buying_power':'900','trading_blocked':False,'account_blocked':False,'status':'ACTIVE'},
                [{'symbol':'AAA','qty':'1','cost_basis':'90','market_value':marks[min(index,len(marks)-1)],
                  'asset_class':'us_equity','side':'long'}], [])
    monkeypatch.setattr(broker,'_account_state',read_state)
    return broker,state,calls


def test_transient_separate_endpoint_marks_recover_without_relaxing_equity_check(wire,monkeypatch):
    from tradingagents.research.account_rounding import equity_reconciles
    broker,state,calls=snapshot_marks(wire,monkeypatch,['100.20','100.20','100','100'])
    snapshot=broker.paper_snapshot()
    assert len(calls)==4 and snapshot.equity_usd==D('1000')
    assert snapshot.positions[0].market_value_usd==D('100') and equity_reconciles(snapshot)
    assert any('"residual_usd": "-0.20"' in x for x in snapshot.limitations)
    assert not state['posts'] and not state['deletes']


def test_persistent_mark_mismatch_stops_after_bounded_reads_without_adjusting_values(wire,monkeypatch):
    from tradingagents.ui.brokers.alpaca import SnapshotConsistencyError
    broker,state,calls=snapshot_marks(wire,monkeypatch,['100.20'])
    with pytest.raises(SnapshotConsistencyError) as failure:broker.paper_snapshot()
    assert len(calls)==10 and len(failure.value.diagnostics)==5
    assert all(d['residual_usd']=='-0.20' for d in failure.value.diagnostics)
    assert not state['posts'] and not state['deletes']


def test_cash_change_between_mark_retries_is_not_hidden(wire,monkeypatch):
    broker,state,calls=snapshot_marks(wire,monkeypatch,['100.20'],cash_changes=True)
    with pytest.raises(ValueError,match='changed during observation'):broker.paper_snapshot()
    assert len(calls)==3 and not state['posts'] and not state['deletes']
