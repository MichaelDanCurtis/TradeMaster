from decimal import Decimal as D

from fastapi.testclient import TestClient

from tradingagents.research.accounting_contracts import AccountActivity
from tradingagents.ui.api import create_app
from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.models import now_utc


def setup(tmp_path):
    broker=FakePaperBroker()
    client=TestClient(create_app(f"sqlite:///{tmp_path/'accounting.db'}",broker_providers={"fixture-paper-broker":broker}))
    return client,broker


def enroll(client):
    preview=client.post("/api/paper-accounting/baselines/preview")
    assert preview.status_code==200,preview.text
    baseline=preview.json()
    response=client.post(f'/api/paper-accounting/baselines/{baseline["baseline_id"]}/approve',json={"actor":"operator","expected_hash":baseline["content_hash"]})
    assert response.status_code==200,response.text
    return response.json()["account_key"]


def test_account_review_is_explicit_and_research_cannot_approve_or_reconcile(tmp_path):
    client,_=setup(tmp_path)
    assert client.get("/api/paper-accounting/accounts").json()=={"accounts":[]}
    assert client.post("/api/paper-accounting/baselines/preview",headers={"x-trademaster-room":"research"}).status_code==403
    baseline=client.post("/api/paper-accounting/baselines/preview").json()
    path=f'/api/paper-accounting/baselines/{baseline["baseline_id"]}/approve'
    assert client.post(path,json={"actor":"operator","expected_hash":"0"*64}).status_code==409
    assert client.post(path,json={"actor":"operator","expected_hash":baseline["content_hash"]},headers={"x-trademaster-room":"research"}).status_code==403
    approved=client.post(path,json={"actor":"operator","expected_hash":baseline["content_hash"]}).json()
    assert client.post(f'/api/paper-accounting/accounts/{approved["account_key"]}/reconcile',headers={"x-trademaster-room":"research"}).status_code==403
    assert client.post("/api/paper-accounting/baselines/preview").status_code==409


def test_approved_manual_fill_reconciles_to_account_and_persists_attribution(tmp_path):
    client,broker=setup(tmp_path)
    key=enroll(client)
    run=client.post("/api/runs",json={"ticker":"AAA","trade_date":"2026-09-04","execution_mode":"simulated","broker_mode":"paper"}).json()
    preview=client.post("/api/trades/preview",json={"run_id":run["run_id"],"symbol":"AAA","side":"buy","notional":650})
    assert preview.status_code==200,preview.text
    preview=preview.json();intent=preview["intent_id"]
    assert client.post(f"/api/trades/{intent}/approve",json={"actor":"operator","expected_order_hash":preview["order_hash"]}).status_code==200
    assert client.post(f"/api/trades/{intent}/submit").json()["status"]=="accepted"
    broker.fill(intent,3)
    broker.positions["AAA"]=broker.positions["AAA"].model_copy(update={"market_value_usd":D(330)})
    result=client.post(f"/api/paper-accounting/accounts/{key}/reconcile")
    assert result.status_code==200,result.text
    report=result.json()["report"]
    assert report["reconciled"] and D(report["investment_pnl_usd"])==30
    assert report["time_weighted_return_fraction"]=="0.0003"
    assert report["attribution"][0]["owner"]=="manual" and D(report["attribution"][0]["period_pnl_usd"])==30
    saved=client.get("/api/paper-accounting/accounts").json()["accounts"][0]
    assert D(saved["latest"]["report"]["investment_pnl_usd"])==30
    assert client.get(f"/api/trades/{intent}/execution").json()["attempt"]["state"]=="partially_filled"
    assert broker.economic_orders==1


def test_unexplained_cash_change_blocks_entries_even_if_raw_fixture_reports_no_drawdown(tmp_path):
    client,broker=setup(tmp_path);key=enroll(client)
    assert client.post(f"/api/paper-accounting/accounts/{key}/reconcile").json()["report"]["reconciled"]
    at=now_utc();broker.cash_usd+=100
    report=client.post(f"/api/paper-accounting/accounts/{key}/reconcile").json()["report"]
    assert not report["reconciled"] and report["investment_pnl_usd"] is None
    run=client.post("/api/runs",json={"ticker":"AAA","trade_date":"2026-09-04","execution_mode":"simulated","broker_mode":"paper"}).json()
    blocked=client.post("/api/trades/preview",json={"run_id":run["run_id"],"symbol":"AAA","side":"buy","notional":100})
    assert blocked.status_code==400 and "drawdown is unavailable" in blocked.json()["detail"]
    # Source arrival explains the cash movement. Without an observed valuation
    # at this flow, dollar P&L recovers but the exact-return gate remains closed.
    broker.activities.append(AccountActivity(source_id="deposit",kind="deposit",cash_amount_usd=100,effective_at=at))
    fixed=client.post(f"/api/paper-accounting/accounts/{key}/reconcile").json()["report"]
    assert fixed["reconciled"] and fixed["investment_pnl_usd"]=="0"
    assert fixed["time_weighted_return_fraction"] is None and fixed["drawdown_fraction"] is None
    assert broker.economic_orders==0


def test_broker_account_switch_cannot_approve_an_old_baseline(tmp_path,monkeypatch):
    client,broker=setup(tmp_path)
    preview=client.post("/api/paper-accounting/baselines/preview").json()
    original=broker.paper_snapshot
    monkeypatch.setattr(broker,"paper_snapshot",lambda:original().model_copy(update={"account_id":"different"}))
    response=client.post(f'/api/paper-accounting/baselines/{preview["baseline_id"]}/approve',json={"actor":"operator","expected_hash":preview["content_hash"]})
    assert response.status_code==409
