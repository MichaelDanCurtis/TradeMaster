"""N-bar channel breakout: stop-entry at channel high, stop at channel midpoint.

Simpler cousin of Donchian-Turtle: enter on a stop-entry at the recent
N-bar high (low for sells); stop sits at the channel midpoint so a clean
retest reverses the trade. Default channel is +/-2% from the reference;
real inputs come from the caller.
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


class ChannelParams(BaseModel):
    channel_high: float | None = Field(default=None, gt=0)
    channel_low: float | None = Field(default=None, gt=0)


@register
class ChannelBreakout(ExecutionAlgorithmBase):
    name = "channel_breakout"
    category = "momentum"
    description = (
        "Stop-entry at the recent channel high; stop at the channel midpoint. "
        "A retest invalidates the breakout cleanly."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = ChannelParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        high = params.channel_high or ctx.reference_price * 1.02
        low = params.channel_low or ctx.reference_price * 0.98
        midpoint = (high + low) / 2
        entry_price = high if ctx.side == "buy" else low
        legs = [
            leg(
                "channel_entry",
                ctx.side,
                ctx.symbol,
                ctx.notional,
                quantity,
                price=entry_price,
                parameters={"trigger_kind": "stop", "channel_high": round(high, 4), "channel_low": round(low, 4)},
            ),
            leg(
                "midpoint_stop",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                price=midpoint,
                parameters={"anchor": "channel_midpoint"},
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
