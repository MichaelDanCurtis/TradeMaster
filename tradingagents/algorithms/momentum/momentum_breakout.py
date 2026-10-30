"""Momentum breakout: stop-buy at a trigger above the recent range; symmetric stop.

Conservative momentum entry: arm a stop order at ``trigger_percent`` above
the reference price (below, for sells). If the breakout never fires the
order never sends. Pairs with a fixed-percent stop on the opposite side so
risk-per-share is defined at submit time.
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


class MomentumBreakoutParams(BaseModel):
    trigger_percent: float = Field(default=1.5, gt=0, le=20)
    stop_percent: float = Field(default=3.0, gt=0, le=20)


@register
class MomentumBreakout(ExecutionAlgorithmBase):
    name = "momentum_breakout"
    category = "momentum"
    description = (
        "Arm a stop-entry above the recent range and a stop-loss below it. "
        "If the breakout fires, you're in; if it doesn't, nothing happens."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = MomentumBreakoutParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        if ctx.side == "buy":
            trigger_price = ctx.reference_price * (1 + params.trigger_percent / 100)
            stop_price = ctx.reference_price * (1 - params.stop_percent / 100)
        else:
            trigger_price = ctx.reference_price * (1 - params.trigger_percent / 100)
            stop_price = ctx.reference_price * (1 + params.stop_percent / 100)
        legs = [
            leg(
                "stop_entry",
                ctx.side,
                ctx.symbol,
                ctx.notional,
                quantity,
                price=trigger_price,
                parameters={"trigger_kind": "stop"},
            ),
            leg(
                "stop_loss",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                price=stop_price,
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
            + ["Order never sends if the breakout fails to trigger."],
        )
