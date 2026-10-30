"""Dual moving-average crossover: market entry assuming a fresh fast-over-slow cross.

This algorithm assumes the user has already confirmed the crossover (the
agent committee or the Lab room produces that signal). The plan is a
single market entry plus a stop placed just below the slow MA value —
exiting if the trend reverses.

When the slow-MA price is not supplied via parameters, falls back to a
default 5% below (above for sells) the reference price.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tradingagents.algorithms.base import (
    STANDARD_POLICY_NOTES,
    AlgorithmContext,
    ExecutionAlgorithmBase,
    ExecutionAlgorithmPlan,
    leg,
    opposite_side,
    quantity_from_notional,
)
from tradingagents.algorithms.registry import register


class DualMAParams(BaseModel):
    slow_ma_price: float | None = Field(default=None, gt=0)
    stop_buffer_percent: float = Field(default=0.5, ge=0, le=10)


@register
class DualMACrossover(ExecutionAlgorithmBase):
    name = "dual_ma_crossover"
    category = "momentum"
    description = (
        "Market entry on confirmed fast-MA-over-slow-MA crossover. "
        "Stop sits just past the slow MA so the trend has to truly reverse to take you out."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = DualMAParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        slow_ma = params.slow_ma_price or _default_slow_ma(ctx.reference_price, ctx.side)
        buf = slow_ma * params.stop_buffer_percent / 100
        stop_price = slow_ma - buf if ctx.side == "buy" else slow_ma + buf
        legs = [
            leg("market_entry", ctx.side, ctx.symbol, ctx.notional, quantity, ctx.reference_price),
            leg(
                "stop_loss",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                price=stop_price,
                parameters={"anchor": "slow_ma", "slow_ma_price": round(slow_ma, 4)},
            ),
        ]
        return ExecutionAlgorithmPlan(
            algorithm=self.name,
            symbol=ctx.symbol,
            side=ctx.side,
            notional=ctx.notional,
            reference_price=round(ctx.reference_price, 4),
            estimated_quantity=quantity,
            legs=legs,
            policy_notes=list(STANDARD_POLICY_NOTES),
        )


def _default_slow_ma(reference_price: float, side: str) -> float:
    return reference_price * 0.95 if side == "buy" else reference_price * 1.05
