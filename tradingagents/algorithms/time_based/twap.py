"""TWAP: time-weighted average price. Equal notional slices on a fixed cadence.

The simplest scheduled execution: divide the parent into N equal slices and
fire one per (window / N) interval. Predictable, ignores volume, can underfill
in thin tape and overfill in heavy tape. The reference price is used as a
fill-estimate price for each slice; in production the broker resolves the
actual print at slice time.
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


class TWAPParams(BaseModel):
    window_minutes: int = Field(default=30, gt=0, le=390)
    slices: int = Field(default=6, ge=1, le=120)


@register
class TWAP(ExecutionAlgorithmBase):
    name = "twap"
    category = "time_based"
    description = (
        "Time-weighted average price. Equal-notional slices on a fixed cadence "
        "over a window. Predictable. Ignores volume."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = TWAPParams(**ctx.parameters)
        slice_seconds = round(params.window_minutes * 60 / params.slices)
        slice_notional = round(ctx.notional / params.slices, 2)
        slice_quantity = round(slice_notional / ctx.reference_price, 6)
        legs = [
            leg(
                "twap_slice",
                ctx.side,
                ctx.symbol,
                slice_notional,
                slice_quantity,
                price=ctx.reference_price,
                parameters={
                    "offset_seconds": i * slice_seconds,
                    "slice_index": i,
                    "total_slices": params.slices,
                },
            )
            for i in range(params.slices)
        ]
        _absorb_remainder(legs, ctx.notional, ctx.reference_price)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
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


def _absorb_remainder(legs: list, target_notional: float, price: float) -> None:
    """Make the last slice absorb rounding remainder so notionals tie out exactly."""

    actual = sum(s.notional for s in legs)
    delta = round(target_notional - actual, 2)
    if delta:
        legs[-1].notional = round(legs[-1].notional + delta, 2)
        legs[-1].estimated_quantity = round(legs[-1].notional / price, 6)
