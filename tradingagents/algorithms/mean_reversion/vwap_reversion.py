"""VWAP reversion: fade large deviations below (above) intraday VWAP.

Counter-trend intraday strategy: when price is significantly below the
session VWAP, the empirical pattern is that intraday flows often pull it
back to that anchor. Enter at the reference price; take profit at the
VWAP; stop beyond the extreme by ``stop_buffer_percent``.
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


class VWAPReversionParams(BaseModel):
    intraday_vwap: float | None = Field(default=None, gt=0)
    stop_buffer_percent: float = Field(default=0.5, gt=0, le=5)


@register
class VWAPReversion(ExecutionAlgorithmBase):
    name = "vwap_reversion"
    category = "mean_reversion"
    description = (
        "Fade intraday deviations from VWAP. Targets the VWAP anchor; stops beyond the deviation."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = VWAPReversionParams(**ctx.parameters)
        vwap = params.intraday_vwap or (
            ctx.reference_price * 1.005 if ctx.side == "buy" else ctx.reference_price * 0.995
        )
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        buffer_amount = ctx.reference_price * params.stop_buffer_percent / 100
        stop_price = (
            ctx.reference_price - buffer_amount
            if ctx.side == "buy"
            else ctx.reference_price + buffer_amount
        )
        legs = [
            leg(
                "limit_entry",
                ctx.side,
                ctx.symbol,
                ctx.notional,
                quantity,
                ctx.reference_price,
                parameters={"intraday_vwap": round(vwap, 4)},
            ),
            leg(
                "take_profit",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                vwap,
                parameters={"anchor": "intraday_vwap"},
            ),
            leg(
                "stop_loss",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                stop_price,
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
