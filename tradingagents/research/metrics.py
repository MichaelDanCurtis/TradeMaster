"""Finite, explicitly qualified metrics from reconciled account history."""
from __future__ import annotations

from decimal import Decimal
from math import ceil, sqrt
from statistics import mean, stdev

from pydantic import Field

from tradingagents.research.contracts import Contract
from tradingagents.research.engines.base import ReplayResult


class PerformanceMetrics(Contract):
    observations: int
    fills: int
    total_return_fraction: float | None
    annualized_return_fraction: float | None
    annualized_volatility_fraction: float | None
    sharpe_ratio: float | None
    max_drawdown_fraction: float | None
    mean_exposure_fraction: float | None
    fees_usd: Decimal
    slippage_usd: Decimal
    stale_valuation_sessions: int
    # Optional defaults preserve old immutable report readability. New reports
    # always compute these fields or explain why the statistic is undefined.
    max_underwater_sessions: int | None = None
    current_underwater_sessions: int | None = None
    worst_session_return_fraction: float | None = None
    mean_worst_five_percent_fraction: float | None = None
    gross_traded_notional_usd: Decimal | None = None
    gross_turnover_fraction: float | None = None
    undefined: dict[str, str] = Field(default_factory=dict)


def daily_returns(result: ReplayResult) -> list[float]:
    previous = result.initial_capital_usd
    returns = []
    for point in result.equity:
        if previous <= 0:
            raise ValueError("nonpositive equity has no defined percentage return")
        returns.append(float(point.equity_usd / previous - 1))
        previous = point.equity_usd
    return returns


def performance(result: ReplayResult, *, cash_returns: list[float] | None = None) -> PerformanceMetrics:
    returns = daily_returns(result)
    unknown = {}
    total = annual = volatility = sharpe = drawdown = exposure = None
    longest = ongoing = worst = tail = None
    if not returns:
        unknown = {name: "No evaluated trading sessions" for name in ("total_return", "annualized_return", "volatility", "sharpe", "drawdown", "exposure")}
        unknown.update({name: "No evaluated trading sessions" for name in ("underwater_sessions", "worst_session_return", "mean_worst_five_percent")})
    else:
        total = float(result.equity[-1].equity_usd / result.initial_capital_usd - 1)
        days = (result.equity[-1].at - result.equity[0].at).total_seconds() / 86400
        if days >= 365 and total > -1:
            annual = (1 + total) ** (365.2425 / days) - 1
        else:
            unknown["annualized_return"] = "At least one calendar year is required; use period return"
        peak = result.initial_capital_usd
        drawdown = 0.0
        longest = ongoing = 0
        for point in result.equity:
            ongoing = ongoing + 1 if point.equity_usd < peak else 0
            longest = max(longest, ongoing)
            peak = max(peak, point.equity_usd)
            drawdown = max(drawdown, float(1 - point.equity_usd / peak))
        worst = min(returns)
        if len(returns) >= 20:
            tail = mean(sorted(returns)[:ceil(len(returns) * .05)])
        else:
            unknown["mean_worst_five_percent"] = "At least twenty observed sessions are required; this is a descriptive sample tail, not a forecast"
        exposure = mean(float(p.market_value_usd / p.equity_usd) for p in result.equity)
        if len(returns) > 1:
            volatility = stdev(returns) * sqrt(252)
        else:
            unknown["volatility"] = "At least two observations are required"
        if cash_returns is None or len(cash_returns) != len(returns):
            unknown["sharpe"] = "A matching cash reference is required"
        elif len(returns) > 1:
            excess = [r - c for r, c in zip(returns, cash_returns)]
            sd = stdev(excess)
            if sd > 1e-12:
                sharpe = mean(excess) / sd * sqrt(252)
            else:
                unknown["sharpe"] = "Excess-return variance is zero"
        else:
            unknown["sharpe"] = "At least two observations are required"
    traded = sum((abs(fill.quantity) * fill.price_usd for fill in result.fills), Decimal(0))
    turnover = float(traded / result.initial_capital_usd) if result.initial_capital_usd > 0 else None
    if turnover is None:
        unknown["gross_turnover"] = "Positive opening capital is required"
    return PerformanceMetrics(
        observations=len(returns), fills=len(result.fills), total_return_fraction=total,
        annualized_return_fraction=annual, annualized_volatility_fraction=volatility,
        sharpe_ratio=sharpe, max_drawdown_fraction=drawdown, mean_exposure_fraction=exposure,
        fees_usd=sum((f.fee_usd for f in result.fills), Decimal(0)),
        slippage_usd=sum((f.slippage_usd for f in result.fills), Decimal(0)),
        stale_valuation_sessions=sum(bool(p.stale_instruments) for p in result.equity), undefined=unknown,
        max_underwater_sessions=longest, current_underwater_sessions=ongoing,
        worst_session_return_fraction=worst, mean_worst_five_percent_fraction=tail,
        gross_traded_notional_usd=traded, gross_turnover_fraction=turnover,
    )
