"""MACD signal-line cross: market entry on signal cross, stop at recent swing.

Assumes the upstream agent has detected a MACD-line crosses-above-signal
event (or vice versa for sell). Stop sits at the recent swing low (high
for sells); if not provided, defaults to 4% below (above) the reference.
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


class MACDParams(BaseModel):
    recent_swing_price: float | None = Field(default=None, gt=0)
    default_swing_percent: float = Field(default=4.0, gt=0, le=20)


@register
class MACDSignal(ExecutionAlgorithmBase):
    name = "macd_signal"
    category = "momentum"
    description = (
        "Entry on MACD/signal-line cross; stop at recent swing. "
        "Pairs trend-confirmation entry with structural-level exit."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = MACDParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        if params.recent_swing_price is not None:
            stop_price = params.recent_swing_price
        elif ctx.side == "buy":
            stop_price = ctx.reference_price * (1 - params.default_swing_percent / 100)
        else:
            stop_price = ctx.reference_price * (1 + params.default_swing_percent / 100)
        legs = [
            leg("market_entry", ctx.side, ctx.symbol, ctx.notional, quantity, ctx.reference_price),
            leg(
                "stop_loss",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                price=stop_price,
                parameters={"anchor": "recent_swing"},
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
