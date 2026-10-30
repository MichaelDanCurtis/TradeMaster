from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from tradingagents.research.contracts import CostScenario, StrategySpec, canonical_json
from tradingagents.research.data.contracts import CorporateAction, DatasetBundle, MarketBar, SecurityMapping, TradingSession
from tradingagents.research.engines.base import EngineUnavailable, ReplayRequest
from tradingagents.research.engines.replay import LocalReplayEngine
from tradingagents.research.metrics import daily_returns, performance
from tests.research.conftest import spec_payload

D = Decimal


def request_fixture(**updates):
    days = [date(2020, 1, 2) + timedelta(days=n) for n in range(30)]
    days = [d for d in days if d.weekday() < 5 and d != date(2020, 1, 20)]
    sessions = [TradingSession(date=d, opens_at=datetime.combine(d, time(14, 30), timezone.utc), closes_at=datetime.combine(d, time(21), timezone.utc)) for d in days]
    bars = [MarketBar(instrument_id="etf_a", session=s.date, open=100+i, high=102+i, low=99+i, close=101+i, volume=1000, available_at=s.closes_at + timedelta(seconds=1)) for i, s in enumerate(sessions)]
    data = DatasetBundle(timezone="America/New_York", sessions=sessions, bars=bars,
        mappings=[SecurityMapping(instrument_id="etf_a", symbol="AAA", valid_from=days[0], known_at=sessions[0].opens_at)])
    spec = StrategySpec.model_validate(spec_payload())
    spec.risk.max_position_fraction = D("0.4")
    return ReplayRequest(dataset=data, spec=spec, start=date(2020, 1, 10), end=date(2020, 1, 14), initial_capital_usd=1000,
        cash_annual_yield_fraction=0, scenario=CostScenario(name="base", slippage_bps=0, commission_usd=1), **updates)


def test_quantity_uses_friday_close_and_fill_uses_monday_open_with_exact_costs():
    request = request_fixture()
    request.scenario.slippage_bps = D(10)
    result = LocalReplayEngine().run(request)
    assert len(result.fills) == 1
    fill = result.fills[0]
    # Jan 10 is bar 6: close 107, so floor(1000 * .4 / 107) = 3.
    # Jan 13 open is 107: 3 * 107 * 1.001 + $1 commission.
    assert fill.quantity == 3 and fill.price_usd == D("107.107")
    assert fill.signal_at.date() == date(2020, 1, 10)
    assert fill.executed_at.date() == date(2020, 1, 13)
    assert fill.observed_at > fill.executed_at > fill.signal_at
    assert result.equity[-1].cash_usd == D("677.679")
    assert result.equity[-1].equity_usd == D("1004.679")
    assert result.equity[-1].fees_usd == 1
    assert result.equity[-1].unrealized_pnl_usd == D("5.679")
    assert canonical_json(result) == canonical_json(LocalReplayEngine().run(request))


def proportional_request():
    request=request_fixture()
    request.end=date(2020,1,22)
    request.scenario.commission_usd=D('0.25')
    request.scenario.commission_bps=D(1)
    request.scenario.slippage_bps=D(10)
    for bar in request.dataset.bars:
        if bar.session>=date(2020,1,14):
            decline=D((bar.session-date(2020,1,14)).days)*2
            for field in ('open','high','low','close'):setattr(bar,field,getattr(bar,field)/2-decline)
    return request


def test_proportional_commissions_charge_both_sides_and_reconcile_cash_and_pnl():
    result=LocalReplayEngine().run(proportional_request())
    assert any(f.quantity>0 for f in result.fills) and any(f.quantity<0 for f in result.fills)
    cash=D(1000);fees=D(0)
    for fill in result.fills:
        expected=D('0.25')+abs(fill.quantity)*fill.price_usd*D('0.0001')
        assert fill.fee_usd==expected
        fees+=expected;cash-=fill.quantity*fill.price_usd+expected
    final=result.equity[-1]
    assert final.quantities=={'etf_a':0}
    assert final.cash_usd==final.equity_usd==cash
    assert final.fees_usd==fees
    assert final.equity_usd==D(1000)+final.realized_pnl_usd-fees


def test_split_pending_quantities_and_dividend_receivable_reconcile_without_early_cash():
    request = request_fixture()
    monday = next(s for s in request.dataset.sessions if s.date == date(2020, 1, 13))
    tuesday = next(s for s in request.dataset.sessions if s.date == date(2020, 1, 14))
    request.dataset.actions = [
        CorporateAction(action_id="split", instrument_id="etf_a", kind="split", effective_session=monday.date, available_at=monday.opens_at, split_ratio=2),
        CorporateAction(action_id="dividend", instrument_id="etf_a", kind="dividend", effective_session=tuesday.date, available_at=tuesday.opens_at, cash_per_share_usd=1, payable_at=tuesday.closes_at+timedelta(days=1)),
    ]
    for bar in request.dataset.bars:
        if bar.session >= monday.date:
            for field in ("open", "high", "low", "close"):
                setattr(bar, field, getattr(bar, field)/2 - (1 if bar.session >= tuesday.date else 0))
    result = LocalReplayEngine().run(request)
    assert result.fills[0].quantity == 6
    final = result.equity[-1]
    assert final.cash_usd == 678 and final.receivables_usd == 6
    assert final.equity_usd == 1005 and final.dividends_usd == 6
    assert not any(e.kind == "payment" for e in result.events)
    request.end = date(2020, 1, 15)
    paid = LocalReplayEngine().run(request)
    assert paid.equity[-1].cash_usd == 684 and paid.equity[-1].receivables_usd == 0


def test_future_open_cannot_resize_previous_order_and_gap_can_make_it_unfilled():
    request = request_fixture()
    original = LocalReplayEngine().run(request)
    for bar in request.dataset.bars:
        if bar.session >= date(2020, 1, 13):
            for field in ("open", "high", "low", "close"):
                setattr(bar, field, getattr(bar, field)*3)
    gap = LocalReplayEngine().run(request)
    assert gap.decisions[0] == original.decisions[0]
    assert gap.fills == []
    assert any("cap or cash reserve" in e.detail for e in gap.events if e.kind == "unfilled")
    assert gap.equity[-1].cash_usd == 1000


def test_holiday_calendar_and_delayed_scenario_cannot_use_same_session_fill():
    request = request_fixture()
    request.start, request.end = date(2020, 1, 17), date(2020, 1, 23)
    base = LocalReplayEngine().run(request)
    assert base.fills[0].executed_at.date() == date(2020, 1, 21)
    request.scenario.execution_delay_sessions = 1
    delayed = LocalReplayEngine().run(request)
    assert delayed.fills[0].executed_at.date() == date(2020, 1, 22)
    assert delayed.decisions[0].proposed_quantities == base.decisions[0].proposed_quantities


def test_missing_bar_stays_visible_in_equity_and_no_warmup_does_not_fabricate_a_trade():
    request = request_fixture()
    request.dataset.bars = [b for b in request.dataset.bars if b.session != date(2020, 1, 14)]
    result = LocalReplayEngine().run(request)
    assert result.equity[-1].stale_instruments == ["etf_a"]
    assert performance(result).stale_valuation_sessions == 1
    request = request_fixture()
    request.spec.rules.lookbacks_sessions = [252]
    result = LocalReplayEngine().run(request)
    cash = LocalReplayEngine().run(request.model_copy(update={"control": "cash"}))
    metrics = performance(result, cash_returns=daily_returns(cash))
    assert result.fills == [] and metrics.total_return_fraction == 0
    assert metrics.sharpe_ratio is None and "zero" in metrics.undefined["sharpe"]
    assert "NaN" not in canonical_json(metrics)


def test_late_corporate_action_is_an_explicit_unavailable_result():
    request = request_fixture()
    session = request.dataset.sessions[7]
    request.dataset.actions.append(CorporateAction(action_id="late", instrument_id="etf_a", kind="split", effective_session=session.date, available_at=session.closes_at, split_ratio=2))
    with pytest.raises(EngineUnavailable, match="unavailable at its effective open"):
        LocalReplayEngine().run(request)


def test_drawdown_pause_preserves_positions_and_never_silently_liquidates():
    request = request_fixture()
    request.end = date(2020, 1, 22)
    request.spec.risk.max_drawdown_fraction = D("0.05")
    for bar in request.dataset.bars:
        if bar.session >= date(2020, 1, 14):
            for field in ("open", "high", "low", "close"):
                setattr(bar, field, getattr(bar, field)/2)
    result = LocalReplayEngine().run(request)
    pauses = [e for e in result.events if e.kind == "risk_pause"]
    assert pauses and pauses[0].at.date() == date(2020, 1, 14)
    assert result.equity[2].quantities["etf_a"] == 3
    assert not [f for f in result.fills if f.executed_at.date() == date(2020, 1, 14)]
    assert not [f for f in result.fills if f.executed_at >= pauses[0].at and f.quantity > 0]


def test_receivable_payment_before_entitlement_is_rejected():
    request = request_fixture()
    monday = request.dataset.sessions[7]
    request.dataset.actions.append(CorporateAction(action_id="bad", instrument_id="etf_a", kind="dividend", effective_session=monday.date, available_at=monday.opens_at, cash_per_share_usd=1, payable_at=monday.opens_at-timedelta(days=1)))
    with pytest.raises(ValueError, match="payment cannot precede"):
        DatasetBundle.model_validate(request.dataset.model_dump(mode="json"))


def test_reverse_split_of_held_shares_reconciles_fractional_cash_and_cost_basis():
    request = request_fixture()
    session = next(s for s in request.dataset.sessions if s.date == date(2020, 1, 14))
    request.dataset.actions.append(CorporateAction(action_id="reverse", instrument_id="etf_a", kind="split", effective_session=session.date, available_at=session.opens_at, split_ratio=".5"))
    for bar in request.dataset.bars:
        if bar.session >= session.date:
            for field in ("open", "high", "low", "close"):
                setattr(bar, field, getattr(bar, field)*2)
    result = LocalReplayEngine().run(request)
    point = result.equity[-1]
    # Three shares bought for $321 become 1.5 shares. Half a share pays
    # .5 * $216 = $108 at the open and releases $107 of original basis.
    assert point.quantities["etf_a"] == 1
    assert point.cash_usd == 786 and point.cost_basis_usd == 214
    assert point.realized_pnl_usd == 1 and point.unrealized_pnl_usd == 4
    assert point.equity_usd == 1004


def test_delisting_with_zero_recovery_is_a_loss_not_a_dropped_position():
    request = request_fixture()
    session = next(s for s in request.dataset.sessions if s.date == date(2020, 1, 14))
    request.dataset.actions.append(CorporateAction(action_id="delisted", instrument_id="etf_a", kind="delisting", effective_session=session.date, available_at=session.opens_at, cash_per_share_usd=0, payable_at=session.opens_at))
    result = LocalReplayEngine().run(request)
    point = result.equity[-1]
    assert point.quantities["etf_a"] == 0 and point.cost_basis_usd == 0
    assert point.realized_pnl_usd == -321 and point.equity_usd == 678
    assert any(e.kind == "delisting" for e in result.events)
