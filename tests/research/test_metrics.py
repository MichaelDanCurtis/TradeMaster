from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from tradingagents.research.engines.base import EquityPoint, Fill, ReplayResult
from tradingagents.research.metrics import PerformanceMetrics, performance


def account(values, fills=()):
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    points = [EquityPoint(at=start + timedelta(days=index), equity_usd=value, cash_usd=value,
        receivables_usd=0, market_value_usd=0, cost_basis_usd=0, realized_pnl_usd=0,
        unrealized_pnl_usd=0, dividends_usd=0, cash_yield_usd=0, fees_usd=0, quantities={})
        for index, value in enumerate(values)]
    return ReplayResult(engine_build="metric_fixture", control="cash", initial_capital_usd=100,
        decisions=[], fills=list(fills), events=[], equity=points, limitations=["Metric arithmetic fixture"])


def test_underwater_spells_count_initial_loss_reset_at_recovery_and_preserve_censoring():
    result = performance(account([90, 95, 100, 110, 99, 99]))
    assert result.max_underwater_sessions == 2 and result.current_underwater_sessions == 2
    assert result.max_drawdown_fraction == pytest.approx(.1)
    assert result.worst_session_return_fraction == pytest.approx(-.1)
    assert result.mean_worst_five_percent_fraction is None
    assert "twenty" in result.undefined["mean_worst_five_percent"]
    recovered = performance(account([90, 95, 100, 110, 99, 110]))
    assert recovered.max_underwater_sessions == 2 and recovered.current_underwater_sessions == 0


def test_sample_tail_rounds_count_up_and_retains_loss_sign():
    # Twenty-one returns: -10%, -5%, and nineteen zeros. ceil(21*.05)=2.
    result = performance(account([D(90)] + [D("85.5")] * 20))
    assert result.mean_worst_five_percent_fraction == pytest.approx(-.075)
    assert result.worst_session_return_fraction == pytest.approx(-.1)
    assert result.current_underwater_sessions == 21


def test_gross_turnover_adds_both_sides_without_fees_or_halving():
    at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    def fill(identifier, quantity, price):
        return Fill(fill_id=identifier, decision_id="decision", instrument_id="instrument", signal_at=at,
            executed_at=at + timedelta(days=1), observed_at=at + timedelta(days=1), quantity=quantity,
            price_usd=price, fee_usd=7, slippage_usd=3, realized_pnl_usd=0)
    result = performance(account([100], [fill("buy", 3, D("10.10")), fill("sell", -2, D("12.25"))]))
    assert result.gross_traded_notional_usd == D("54.80")
    assert result.gross_turnover_fraction == pytest.approx(.548)
    assert result.fees_usd == 14 and result.slippage_usd == 6


def test_empty_cash_only_and_old_reports_keep_unknown_separate_from_zero():
    empty = performance(account([]))
    assert empty.max_underwater_sessions is None and empty.worst_session_return_fraction is None
    assert empty.gross_turnover_fraction == 0  # A complete empty fill ledger, not an inferred return.
    flat = performance(account([100] * 20), cash_returns=[0] * 20)
    assert flat.max_underwater_sessions == flat.current_underwater_sessions == 0
    assert flat.mean_worst_five_percent_fraction == flat.worst_session_return_fraction == 0
    assert flat.sharpe_ratio is None and "zero" in flat.undefined["sharpe"]
    legacy = flat.model_dump(exclude={"max_underwater_sessions", "current_underwater_sessions", "worst_session_return_fraction",
        "mean_worst_five_percent_fraction", "gross_traded_notional_usd", "gross_turnover_fraction"})
    restored = PerformanceMetrics.model_validate(legacy)
    assert restored.max_underwater_sessions is None and restored.gross_turnover_fraction is None
