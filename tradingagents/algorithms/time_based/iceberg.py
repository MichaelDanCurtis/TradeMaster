"""Iceberg: hide most of the size; show only the tip.

The total parent is split into N slices. Only ``visible_slices`` are exposed
on the book at any time; as each visible slice fills, the next hidden one
replaces it. The plan describes every planned slice so the audit trail
captures the intent; the broker is responsible for the actual visible/hidden
rotation.

Useful when the parent size is large enough relative to top-of-book depth
that revealing it would walk the price.
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


class IcebergParams(BaseModel):
    total_slices: int = Field(default=8, ge=2, le=64)
    visible_slices: int = Field(default=2, ge=1, le=32)


@register
class Iceberg(ExecutionAlgorithmBase):
    name = "iceberg"
    category = "time_based"
    description = (
        "Show only the tip; refill from hidden inventory as fills happen. "
        "Reduces information leakage for block-sized parents."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = IcebergParams(**ctx.parameters)
        if params.visible_slices > params.total_slices:
            raise ValueError("visible_slices cannot exceed total_slices")
        slice_notional = round(ctx.notional / params.total_slices, 2)
        slice_quantity = round(slice_notional / ctx.reference_price, 6)
        legs = [
            leg(
                "iceberg_slice",
                ctx.side,
                ctx.symbol,
                slice_notional,
                slice_quantity,
                price=ctx.reference_price,
                parameters={
                    "slice_index": i,
                    "visible_at_start": str(i < params.visible_slices),
                    "total_slices": params.total_slices,
                },
            )
            for i in range(params.total_slices)
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
                f"Iceberg shows {params.visible_slices}/{params.total_slices} slices at a time."
            ],
        )


def _absorb_remainder(legs: list, target_notional: float, price: float) -> None:
    actual = sum(s.notional for s in legs)
    delta = round(target_notional - actual, 2)
    if delta:
        legs[-1].notional = round(legs[-1].notional + delta, 2)
        legs[-1].estimated_quantity = round(legs[-1].notional / price, 6)
