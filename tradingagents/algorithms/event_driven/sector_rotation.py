"""Sector rotation: enter only if the parent ticker's sector is currently leading.

Multi-month sector relative-strength: rank sectors by 3-month return; only
allow entries in the top-quartile sector. The caller supplies the sector
ranking via parameters; this algorithm gates the trade and shapes the
remainder.

Inputs (via parameters):
- ``sector_rank``: integer rank of this ticker's sector (1 = best)
- ``total_sectors``: how many sectors in the universe (default 11 GICS)
- ``max_eligible_rank``: cutoff to enter (default 3 — top 3 sectors only)
- ``trail_percent``: trailing-stop distance (default 6%)
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


class SectorRotationParams(BaseModel):
    sector_rank: int = Field(default=1, ge=1, le=20)
    total_sectors: int = Field(default=11, ge=2, le=30)
    max_eligible_rank: int = Field(default=3, ge=1, le=20)
    trail_percent: float = Field(default=6.0, gt=0, le=50)


@register
class SectorRotation(ExecutionAlgorithmBase):
    name = "sector_rotation"
    category = "event_driven"
    description = (
        "Sector relative-strength gate. Only enters when the ticker's sector is "
        "in the top N of the rolling 3-month rank; trailing-stop carries the trend."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = SectorRotationParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        eligible = params.sector_rank <= params.max_eligible_rank
        legs: list = []
        notes = list(STANDARD_POLICY_NOTES) + [
            f"Sector rank {params.sector_rank}/{params.total_sectors} (cutoff: top {params.max_eligible_rank})."
        ]
        if not eligible:
            notes.append("Sector outside eligibility band; no entry proposed.")
        else:
            legs.extend(
                [
                    leg(
                        "market_entry",
                        ctx.side,
                        ctx.symbol,
                        ctx.notional,
                        quantity,
                        ctx.reference_price,
                        parameters={
                            "sector_rank": params.sector_rank,
                            "total_sectors": params.total_sectors,
                        },
                    ),
                    leg(
                        "trailing_stop",
                        opposite_side(ctx.side),
                        ctx.symbol,
                        ctx.notional,
                        quantity,
                        price=None,
                        parameters={"trail_percent": params.trail_percent},
                    ),
                ]
            )
        return ExecutionAlgorithmPlan(
            algorithm=self.name,
            symbol=ctx.symbol,
            side=ctx.side,
            notional=ctx.notional if legs else 0.0,
            reference_price=round(ctx.reference_price, 4),
            estimated_quantity=quantity if legs else 0.0,
            legs=legs,
            policy_notes=notes,
        )
