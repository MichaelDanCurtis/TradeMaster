"""POV: percentage-of-volume. Participate as a fixed share of printed volume.

Unlike VWAP (predicted curve), POV reacts to live volume. The broker
participates at ``participation_rate`` of every print until the parent
notional is filled or the cap is reached. The plan describes the
participation contract — broker integration is responsible for the
moment-by-moment slicing.

We split the parent into N equal-notional slices for orderly handoff and
auditability; each slice carries the participation parameters so the
broker can reconcile against the live tape.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tradingagents.algorithms.base import (
    STANDARD_POLICY_NOTES,
    AlgorithmContext,
    ExecutionAlgorithmBase,
    ExecutionAlgorithmPlan,
    leg,
    quantity_from_notional,
)
from tradingagents.algorithms.registry import register


class POVParams(BaseModel):
    participation_rate: float = Field(default=0.10, gt=0, le=0.50)
    expected_session_volume: float = Field(default=10_000_000.0, gt=0)
    max_slices: int = Field(default=12, ge=1, le=120)


@register
class POV(ExecutionAlgorithmBase):
    name = "pov"
    category = "time_based"
    description = (
        "Percentage-of-volume: participate at a fixed share of printed tape. "
        "Adapts to live liquidity; better than VWAP when realized volume diverges from forecast."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = POVParams(**ctx.parameters)
        slice_notional = round(ctx.notional / params.max_slices, 2)
        slice_quantity = round(slice_notional / ctx.reference_price, 6)
        legs = [
            leg(
                "pov_slice",
                ctx.side,
                ctx.symbol,
                slice_notional,
                slice_quantity,
                price=ctx.reference_price,
                parameters={
                    "participation_rate": params.participation_rate,
                    "expected_session_volume": params.expected_session_volume,
                    "slice_index": i,
                    "total_slices": params.max_slices,
                },
            )
            for i in range(params.max_slices)
        ]
        _absorb_remainder(legs, ctx.notional, ctx.reference_price)
        return ExecutionAlgorithmPlan(
            algorithm=self.name,
            symbol=ctx.symbol,
            side=ctx.side,
            notional=ctx.notional,
            reference_price=round(ctx.reference_price, 4),
            estimated_quantity=quantity_from_notional(ctx.notional, ctx.reference_price),
            legs=legs,
            policy_notes=list(STANDARD_POLICY_NOTES)
            + [
                f"Participation capped at {params.participation_rate * 100:.1f}% of printed volume."
            ],
        )


def _absorb_remainder(legs: list, target_notional: float, price: float) -> None:
    actual = sum(s.notional for s in legs)
    delta = round(target_notional - actual, 2)
    if delta:
        legs[-1].notional = round(legs[-1].notional + delta, 2)
        legs[-1].estimated_quantity = round(legs[-1].notional / price, 6)
