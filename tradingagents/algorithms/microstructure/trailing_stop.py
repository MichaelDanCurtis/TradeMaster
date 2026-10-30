"""Trailing-stop: market entry plus an exit guard that trails by a fixed percent.

Behavior preserved exactly from the legacy implementation so the existing
`test_trailing_stop_algorithm_builds_entry_and_stop_legs` test continues to
hold. The trail percent is fixed at 5% in the parameters payload, matching
the legacy hard-coded value; this can be parameterized in a future revision
once a user-controlled UI surfaces it.
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


class TrailingStopParams(BaseModel):
    trail_percent: float = Field(default=5.0, gt=0, le=50)


@register
class TrailingStop(ExecutionAlgorithmBase):
    name = "trailing_stop"
    category = "microstructure"
    description = (
        "Market entry plus a percentage-based trailing-stop guard on the opposite side. "
        "Lets a winning position breathe while capping give-back."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = TrailingStopParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        entry = leg(
            "market_entry",
            ctx.side,
            ctx.symbol,
            ctx.notional,
            quantity,
            ctx.reference_price,
        )
        guard = leg(
            "trailing_stop",
            opposite_side(ctx.side),
            ctx.symbol,
            ctx.notional,
            quantity,
            price=None,
            parameters={"trail_percent": params.trail_percent},
        )
        return ExecutionAlgorithmPlan(
            algorithm=self.name,
            symbol=ctx.symbol,
            side=ctx.side,
            notional=ctx.notional,
            reference_price=round(ctx.reference_price, 4),
            estimated_quantity=quantity,
            legs=[entry, guard],
            policy_notes=list(STANDARD_POLICY_NOTES),
        )
