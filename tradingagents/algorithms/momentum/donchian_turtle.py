"""Donchian-Turtle: classic 20-day high entry with 2×ATR stop.

Modeled on the Turtle trading rules. Entry is a stop order at the
Donchian-channel high (low for sells); stop sits 2 ATRs below entry (above
for sells). Both values can be supplied via parameters; defaults derive
from the reference price.
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


class TurtleParams(BaseModel):
    donchian_high: float | None = Field(default=None, gt=0)
    donchian_low: float | None = Field(default=None, gt=0)
    atr: float | None = Field(default=None, gt=0)
    atr_multiple: float = Field(default=2.0, gt=0, le=10)


@register
class DonchianTurtle(ExecutionAlgorithmBase):
    name = "donchian_turtle"
    category = "momentum"
    description = (
        "Turtle-style breakout: enter on Donchian-high break, stop at entry - N×ATR. "
        "Classic trend-following entry for catching multi-month moves."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = TurtleParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        donchian_high = params.donchian_high or ctx.reference_price * 1.02
        donchian_low = params.donchian_low or ctx.reference_price * 0.98
        atr = params.atr or (donchian_high - donchian_low) / 4
        entry_price = donchian_high if ctx.side == "buy" else donchian_low
        stop_offset = atr * params.atr_multiple
        stop_price = (
            entry_price - stop_offset if ctx.side == "buy" else entry_price + stop_offset
        )
        legs = [
            leg(
                "donchian_entry",
                ctx.side,
                ctx.symbol,
                ctx.notional,
                quantity,
                price=entry_price,
                parameters={"trigger_kind": "stop", "anchor": "donchian"},
            ),
            leg(
                "atr_stop",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                price=stop_price,
                parameters={"atr": round(atr, 4), "atr_multiple": params.atr_multiple},
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
            policy_notes=list(STANDARD_POLICY_NOTES)
            + ["Turtle entry: skip if breakout never fires."],
        )
