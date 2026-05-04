from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


TradeSide = Literal["buy", "sell"]
TradeEnvironment = Literal["paper", "live"]


class TradeProposal(BaseModel):
    symbol: str
    side: TradeSide
    notional: float = Field(gt=0)
    environment: TradeEnvironment
    sector: str | None = None


class ConstraintContext(BaseModel):
    account_equity: float = Field(gt=0)
    current_position_notional: float = Field(ge=0)
    sector_exposure_notional: float = Field(ge=0)
    daily_turnover_notional: float = Field(ge=0)
    current_drawdown_percent: float = Field(ge=0)


class PortfolioConstraintPolicy(BaseModel):
    max_position_percent: float = Field(gt=0, le=100)
    max_sector_percent: float = Field(gt=0, le=100)
    max_daily_turnover_percent: float = Field(gt=0, le=100)
    max_drawdown_percent: float = Field(ge=0, le=100)
    paper_mode_required: bool = True


class ConstraintViolation(BaseModel):
    rule: str
    message: str
    observed: float | str | bool
    limit: float | str | bool


class ConstraintDecision(BaseModel):
    passed: bool
    violations: list[ConstraintViolation]


class SymbolicConstraintEngine:
    def evaluate(
        self,
        proposal: TradeProposal,
        context: ConstraintContext,
        policy: PortfolioConstraintPolicy,
    ) -> ConstraintDecision:
        violations: list[ConstraintViolation] = []

        if policy.paper_mode_required and proposal.environment != "paper":
            violations.append(
                ConstraintViolation(
                    rule="paper_mode_required",
                    message="Policy requires paper trading.",
                    observed=proposal.environment,
                    limit="paper",
                )
            )

        next_position_percent = _percent(
            context.current_position_notional + _buy_notional(proposal),
            context.account_equity,
        )
        if next_position_percent > policy.max_position_percent:
            violations.append(
                ConstraintViolation(
                    rule="max_position_percent",
                    message="Position concentration limit breached.",
                    observed=next_position_percent,
                    limit=policy.max_position_percent,
                )
            )

        next_sector_percent = _percent(
            context.sector_exposure_notional + _buy_notional(proposal),
            context.account_equity,
        )
        if next_sector_percent > policy.max_sector_percent:
            violations.append(
                ConstraintViolation(
                    rule="max_sector_percent",
                    message="Sector concentration limit breached.",
                    observed=next_sector_percent,
                    limit=policy.max_sector_percent,
                )
            )

        next_turnover_percent = _percent(
            context.daily_turnover_notional + proposal.notional,
            context.account_equity,
        )
        if next_turnover_percent > policy.max_daily_turnover_percent:
            violations.append(
                ConstraintViolation(
                    rule="max_daily_turnover_percent",
                    message="Daily turnover limit breached.",
                    observed=next_turnover_percent,
                    limit=policy.max_daily_turnover_percent,
                )
            )

        if context.current_drawdown_percent > policy.max_drawdown_percent:
            violations.append(
                ConstraintViolation(
                    rule="max_drawdown_percent",
                    message="Drawdown circuit breaker breached.",
                    observed=context.current_drawdown_percent,
                    limit=policy.max_drawdown_percent,
                )
            )

        return ConstraintDecision(passed=not violations, violations=violations)


def _buy_notional(proposal: TradeProposal) -> float:
    return proposal.notional if proposal.side == "buy" else 0


def _percent(numerator: float, denominator: float) -> float:
    return (numerator / denominator) * 100
