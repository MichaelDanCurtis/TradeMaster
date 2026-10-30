from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from tradingagents.research.accounting import reconcile_account
from tradingagents.research.accounting_contracts import AccountActivity
from tradingagents.research.execution_contracts import AccountPosition, PaperAccountSnapshot

START = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def snapshot(seconds, cash, positions=None):
    positions = positions or []
    return PaperAccountSnapshot(provider_id="fixture", account_id="account", evidence_kind="fixture", started_at=START+timedelta(seconds=seconds), observed_at=START+timedelta(seconds=seconds),
        equity_usd=D(cash)+sum((p.market_value_usd for p in positions),D(0)), cash_usd=cash, buying_power_usd=cash, daily_turnover_usd=0, drawdown_fraction=None, trading_blocked=False,
        positions=positions, open_orders=[], complete=True)


def position(symbol, qty, basis, value):
    return AccountPosition(symbol=symbol, quantity=qty, cost_basis_usd=basis, market_value_usd=value)


def activity(second, kind, **kwargs):
    return AccountActivity(source_id=f"activity-{second}", effective_at=START+timedelta(seconds=second), kind=kind, **kwargs)


def test_split_dividend_partial_exit_fees_and_income_reconcile_by_hand():
    events = [
        activity(1,"fill",symbol="AAA",side="buy",quantity=4,price_usd=100,fee_usd=1,broker_order_id="entry"),
        activity(2,"split",symbol="AAA",split_ratio=2),
        activity(3,"dividend",symbol="AAA",cash_amount_usd=8,entitlement_at=START+timedelta(seconds=2)),
        activity(4,"fill",symbol="AAA",side="sell",quantity=3,price_usd=60,fee_usd=2,broker_order_id="exit"),
        activity(5,"fee",cash_amount_usd=-1,broker_order_id="entry"),
        activity(6,"interest",cash_amount_usd=2),
    ]
    report = reconcile_account(snapshot(0,1000), [snapshot(7,786,[position("AAA",5,250,325)])],events,{"entry":"deployment:trend", "exit":"manual"})
    assert report["reconciled"], report["discrepancies"]
    assert report["equity_usd"] == 1111 and report["investment_pnl_usd"] == 111
    assert report["realized_pnl_usd"] == 30 and report["unrealized_pnl_usd"] == 75
    assert report["income_usd"] == 10 and report["fees_usd"] == 4
    owners = {x["owner"]:x for x in report["attribution"]}
    assert owners["deployment:trend"]["period_pnl_usd"] == 109
    assert owners["unattributed_income"]["period_pnl_usd"] == 2
    assert report["fills"][-1]["executor"] == "manual"
    assert report["fills"][-1]["position_owners"] == {"deployment:trend":3}
    assert report["time_weighted_return_fraction"] == D(".111")


def test_opening_unrealized_gain_is_not_new_period_profit():
    start = snapshot(0,800,[position("AAA",2,100,200)])
    event = activity(1,"fill",symbol="AAA",side="sell",quantity=1,price_usd=110,broker_order_id="outside")
    report = reconcile_account(start,[snapshot(2,910,[position("AAA",1,50,120)])],[event])
    assert report["reconciled"] and report["investment_pnl_usd"] == 30
    assert report["opening_unrealized_pnl_usd"] == 100
    assert report["realized_pnl_usd"] == 60 and report["unrealized_pnl_usd"] == 70
    assert report["attribution"][0]["period_pnl_usd"] == 30


def test_continuous_holding_clock_survives_fifo_lot_sale_split_and_ticker_change():
    events=[activity(1,"fill",symbol="AAA",side="buy",quantity=2,price_usd=100,broker_order_id="first"),
            activity(2,"fill",symbol="AAA",side="buy",quantity=2,price_usd=100,broker_order_id="second"),
            activity(3,"fill",symbol="AAA",side="sell",quantity=2,price_usd=100,broker_order_id="manual"),
            activity(4,"split",symbol="AAA",split_ratio=2),
            activity(5,"symbol_change",symbol="AAA",new_symbol="BBB")]
    report=reconcile_account(snapshot(0,1000),[snapshot(6,800,[position("BBB",4,200,200)])],events,
        {"first":"deployment:test","second":"deployment:test"})
    assert report["reconciled"],report["discrepancies"]
    assert report["position_cycles"]==[{"symbol":"BBB","owner":"deployment:test","entry_source_id":"activity-1",
        "entry_broker_order_id":"first","entry_at":(START+timedelta(seconds=1)).isoformat()}]
    events.extend([activity(7,"fill",symbol="BBB",side="sell",quantity=4,price_usd=50,broker_order_id="exit"),
                   activity(8,"fill",symbol="BBB",side="buy",quantity=1,price_usd=50,broker_order_id="third")])
    report=reconcile_account(snapshot(0,1000),[snapshot(9,950,[position("BBB",1,50,50)])],events,
        {"first":"deployment:test","second":"deployment:test","third":"deployment:test"})
    assert report["reconciled"] and report["position_cycles"][0]["entry_broker_order_id"]=="third"


def test_fractional_split_cash_compensation_and_symbol_change():
    events = [activity(1,"split",symbol="OLD",split_ratio="1.5"),
        activity(2,"cash_in_lieu",symbol="OLD",quantity=".5",cash_amount_usd=10),
        activity(3,"symbol_change",symbol="OLD",new_symbol="NEW")]
    report = reconcile_account(snapshot(0,10,[position("OLD",3,90,90)]),[snapshot(4,20,[position("NEW",4,80,100)])],events)
    assert report["reconciled"] and report["investment_pnl_usd"] == 20
    assert report["realized_pnl_usd"] == 0 and report["positions"][0]["symbol"] == "NEW"


def flow_case(valuations=True):
    events=[activity(1,"interest",cash_amount_usd=100),
        activity(2,"deposit",cash_amount_usd=1000,**({"equity_before_flow_usd":1100,"flow_valuation_reference":"mark-before-deposit"} if valuations else {})),
        activity(3,"interest",cash_amount_usd=210),
        activity(4,"withdrawal",cash_amount_usd=-210,**({"equity_before_flow_usd":2310,"flow_valuation_reference":"mark-before-withdrawal"} if valuations else {})),
        activity(5,"fee",cash_amount_usd=-210)]
    return reconcile_account(snapshot(0,1000),[snapshot(1,1100),snapshot(3,2310),snapshot(6,1890)],events)


def test_external_flows_do_not_inflate_return_and_unitized_drawdown_is_exact():
    report=flow_case()
    assert report["reconciled"] and report["net_external_flows_usd"] == 790
    assert report["investment_pnl_usd"] == 100
    # 10% gain, a deposit, 10% gain, a withdrawal, 10% loss.
    assert abs(report["time_weighted_return_fraction"]-D(".089")) < D("1e-30")
    assert abs(report["maximum_drawdown_fraction"]-D(".1")) < D("1e-30")
    assert abs(report["drawdown_fraction"]-D(".1")) < D("1e-30")


def test_missing_cash_flow_valuation_preserves_dollar_pnl_but_not_exact_return():
    report=flow_case(False)
    assert report["reconciled"] and report["investment_pnl_usd"] == 100
    assert report["time_weighted_return_fraction"] is None and report["drawdown_fraction"] is None
    assert "contemporaneous valuation" in " ".join(report["limitations"])


def test_external_unexplained_holdings_and_unknown_activity_are_not_performance():
    report=reconcile_account(snapshot(0,1000),[snapshot(2,1000,[position("AAA",1,100,100)])],[activity(1,"unknown",raw={"activity_type":"STOCK_TRANSFER"})])
    assert not report["reconciled"]
    assert report["investment_pnl_usd"] is None and report["time_weighted_return_fraction"] is None
    assert {x["code"] for x in report["discrepancies"]} >= {"position_mismatch","unknown_activity","pnl_identity_mismatch"}


def test_fee_reduces_performance_not_external_cash_flow():
    report=reconcile_account(snapshot(0,1000),[snapshot(2,990)],[activity(1,"fee",cash_amount_usd=-10)])
    assert report["reconciled"] and report["investment_pnl_usd"] == -10
    assert report["net_external_flows_usd"] == 0 and report["time_weighted_return_fraction"] == D("-.01")


@pytest.mark.parametrize("kwargs", [{"kind":"deposit","cash_amount_usd":-100}, {"kind":"withdrawal","cash_amount_usd":100}, {"kind":"fill","symbol":"AAA","side":"buy","quantity":0,"price_usd":100,"broker_order_id":"order"}, {"kind":"split","symbol":"AAA","split_ratio":0}])
def test_invalid_cash_flow_signs_and_economic_quantities_are_rejected(kwargs):
    with pytest.raises(ValueError): AccountActivity(source_id="invalid",effective_at=START,**kwargs)


def test_total_equity_loss_is_reported_instead_of_rejected_or_hidden():
    report=reconcile_account(snapshot(0,1000),[snapshot(2,0)],[activity(1,"fee",cash_amount_usd=-1000)])
    assert report["reconciled"] and report["investment_pnl_usd"] == -1000
    assert report["time_weighted_return_fraction"] == -1 and report["drawdown_fraction"] == 1


def test_simultaneous_external_flows_without_ordering_do_not_invent_exact_return():
    first=activity(1,"deposit",cash_amount_usd=100,equity_before_flow_usd=1000,flow_valuation_reference="first")
    second=first.model_copy(update={"source_id":"second","cash_amount_usd":D(200),"equity_before_flow_usd":D(1100)})
    report=reconcile_account(snapshot(0,1000),[snapshot(2,1300)],[first,second])
    assert report["reconciled"] and report["investment_pnl_usd"] == 0
    assert report["time_weighted_return_fraction"] is None and report["drawdown_fraction"] is None


def alpaca_rounding_snapshot(seconds, marked, equity):
    return snapshot(seconds, 100000, [position("AAA", 2, 800, marked)]).model_copy(update={
        "provider_id": "alpaca-paper-broker", "evidence_kind": "broker_paper", "equity_usd": D(equity)})


def test_cent_reported_equity_retains_residual_without_inventing_strategy_profit():
    start = alpaca_rounding_snapshot(0, "821.855771", "100821.86")
    end = alpaca_rounding_snapshot(2, "831.864", "100831.86")
    report = reconcile_account(start, [end], [])
    assert report["reconciled"], report["discrepancies"]
    assert report["investment_pnl_usd"] == D("10")
    assert report["attribution"][0]["period_pnl_usd"] == D("10.008229")
    assert report["reporting_rounding_change_usd"] == D("-.008229")
    assert report["reporting_rounding_history"][0]["reporting_residual_usd"] == D(".004229")
    assert sum(p["period_pnl_usd"] for p in report["attribution"]) + report["reporting_rounding_change_usd"] == report["investment_pnl_usd"]
    assert report["time_weighted_return_fraction"] is not None
    assert start.positions[0].market_value_usd == D("821.855771")


@pytest.mark.parametrize("updates", [
    {"equity_usd": D("100821.87")},
    {"equity_usd": D("100821.864")},
    {"provider_id": "another-broker"},
    {"evidence_kind": "fixture"},
])
def test_equity_rounding_allowance_is_source_and_precision_specific(updates):
    from tradingagents.research.account_rounding import equity_reconciles
    assert not equity_reconciles(alpaca_rounding_snapshot(0, "821.855771", "100821.86").model_copy(update=updates))


def test_reporting_precision_does_not_hide_cash_or_quantity_discrepancies():
    start = alpaca_rounding_snapshot(0, "821.855771", "100821.86")
    end = alpaca_rounding_snapshot(2, "821.855771", "100821.86").model_copy(update={"cash_usd": D("100000.001")})
    report = reconcile_account(start, [end], [])
    assert not report["reconciled"]
    assert "cash_mismatch" in {row["code"] for row in report["discrepancies"]}
    assert report["investment_pnl_usd"] is None
