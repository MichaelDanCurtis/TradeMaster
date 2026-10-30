"""Point-in-time trend targets. No I/O, broker access, or wall-clock reads."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from math import sqrt
from statistics import stdev

from pydantic import Field

from tradingagents.research.contracts import Contract, Fraction, StrategySpec, TrendRules
from tradingagents.research.data.contracts import DatasetBundle
from tradingagents.research.strategies.portfolio_risk import PortfolioRiskEstimate, portfolio_risk


class TargetDecision(Contract):
    status: str
    reason: str
    weights: dict[str, Fraction] = Field(default_factory=dict)
    signals: dict[str, float] = Field(default_factory=dict)
    annualized_volatility: dict[str, float] = Field(default_factory=dict)
    portfolio_risk: PortfolioRiskEstimate | None = None


def cap_weights(raw: dict[str, Decimal], spec: StrategySpec) -> dict[str, Decimal]:
    """Cap positions and groups proportionally; unused allocation stays in cash."""
    budget = Decimal(1) - spec.risk.cash_reserve_fraction
    total = sum(raw.values())
    if total <= 0:
        return {instrument.instrument_id: Decimal(0) for instrument in spec.universe}
    weights = {instrument.instrument_id: min(spec.risk.max_position_fraction, budget * raw.get(instrument.instrument_id, Decimal(0)) / total) for instrument in spec.universe}
    groups: dict[str, list[str]] = {}
    for instrument in spec.universe:
        groups.setdefault(instrument.risk_group, []).append(instrument.instrument_id)
    for ids in groups.values():
        allocation = sum(weights[identifier] for identifier in ids)
        if allocation > spec.risk.max_group_fraction:
            scale = spec.risk.max_group_fraction / allocation
            for identifier in ids:
                weights[identifier] *= scale
    # Round down; limits remain true after serialization and quantity conversion.
    from decimal import ROUND_DOWN
    return {identifier: weight.quantize(Decimal("0.000000000001"), rounding=ROUND_DOWN) for identifier, weight in weights.items()}


def trend_targets(dataset: DatasetBundle, spec: StrategySpec, as_of: datetime, *, control: bool = False) -> TargetDecision:
    if not isinstance(spec.rules, TrendRules):
        raise ValueError("trend targets require trend rules")
    if as_of.tzinfo is None:
        raise ValueError("decision time must include a timezone")
    rules = spec.rules
    window = max(max(rules.lookbacks_sessions), rules.volatility_sessions) + 1
    sessions = [session for session in dataset.sessions if session.closes_at <= as_of]
    if len(sessions) < window:
        return TargetDecision(status="no_signal", reason=f"Need {window} completed sessions for warm-up")
    required = sessions[-window:]
    dates = [session.date for session in required]
    bars = {(bar.instrument_id, bar.session): bar for bar in dataset.bars if bar.available_at <= as_of}
    actions = {}
    for action in dataset.actions:
        if action.available_at <= as_of:
            actions.setdefault((action.instrument_id, action.effective_session), []).append(action)
    raw, signals, volatilities, aligned_returns = {}, {}, {}, {}
    for instrument in spec.universe:
        identifier = instrument.instrument_id
        if dataset.symbol_at(identifier, as_of) is None:
            return TargetDecision(status="no_signal", reason=f"No valid security mapping for {identifier}")
        if any((identifier, day) not in bars for day in dates):
            return TargetDecision(status="no_signal", reason=f"Missing or late bar for {identifier}; holdings require review")
        total_return = [Decimal(1)]
        daily_returns = []
        for previous, day in zip(dates, dates[1:]):
            split, dividend = Decimal(1), Decimal(0)
            for action in actions.get((identifier, day), []):
                if action.kind == "split":
                    split *= action.split_ratio
                elif action.kind == "dividend":
                    dividend += action.cash_per_share_usd
                elif action.kind == "delisting":
                    return TargetDecision(status="no_signal", reason=f"Delisted instrument {identifier} requires portfolio reconciliation")
            # Dividend per post-action share. Signal returns use explicit actions;
            # execution/accounting still use the original raw tradable prices.
            gross_return = (bars[identifier, day].close + dividend) * split / bars[identifier, previous].close
            total_return.append(total_return[-1] * gross_return)
            daily_returns.append(gross_return - 1)
        score = sum(total_return[-1] > total_return[-length - 1] for length in rules.lookbacks_sessions) / len(rules.lookbacks_sessions)
        volatility = stdev([float(value) for value in daily_returns[-rules.volatility_sessions:]]) * sqrt(252)
        volatility = max(float(rules.volatility_floor_fraction), volatility)
        signals[identifier], volatilities[identifier] = score, volatility
        raw[identifier] = Decimal(1) if control else Decimal(str(score)) / Decimal(str(volatility))
        aligned_returns[identifier] = daily_returns[-rules.volatility_sessions:]
    weights = cap_weights(raw, spec)
    estimate = portfolio_risk(aligned_returns, weights, dates[-rules.volatility_sessions:],
        {instrument.instrument_id:instrument.risk_group for instrument in spec.universe})
    return TargetDecision(status="targets", reason="Fixed-basket control" if control else "Completed-session momentum with capped inverse-volatility weights", weights=weights, signals=signals, annualized_volatility=volatilities, portfolio_risk=estimate)
