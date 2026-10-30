"""VWAP: volume-weighted average price. Slices follow the intraday volume curve.

Unlike TWAP, VWAP fires bigger slices when historical volume is heavier
(typically the open and close hours), and smaller slices through the
midday lull. The default profile is a six-bucket U-curve approximating a
6.5-hour US-equity session; callers can override with an arbitrary
`volume_profile` list summing to roughly 1.0 (we normalize either way).
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


# U-curve weights for a 6-bucket 6.5-hour session: heavier at open/close.
DEFAULT_VOLUME_PROFILE: tuple[float, ...] = (0.20, 0.15, 0.12, 0.12, 0.15, 0.26)


class VWAPParams(BaseModel):
    window_minutes: int = Field(default=390, gt=0, le=1440)
    volume_profile: tuple[float, ...] = Field(default=DEFAULT_VOLUME_PROFILE)


@register
class VWAP(ExecutionAlgorithmBase):
    name = "vwap"
    category = "time_based"
    description = (
        "Volume-weighted average price. Slice weights follow an intraday volume "
        "U-curve so bigger fills happen when liquidity is heavier."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = VWAPParams(**ctx.parameters)
        weights = _normalize(params.volume_profile)
        if not weights:
            raise ValueError("vwap volume_profile must contain at least one bucket")
        bucket_seconds = round(params.window_minutes * 60 / len(weights))
        legs = []
        for i, w in enumerate(weights):
            slice_notional = round(ctx.notional * w, 2)
            slice_quantity = round(slice_notional / ctx.reference_price, 6)
            legs.append(
                leg(
                    "vwap_slice",
                    ctx.side,
                    ctx.symbol,
                    slice_notional,
                    slice_quantity,
                    price=ctx.reference_price,
                    parameters={
                        "offset_seconds": i * bucket_seconds,
                        "weight": round(w, 4),
                        "bucket_index": i,
                    },
                )
            )
        _absorb_remainder(legs, ctx.notional, ctx.reference_price)
        return ExecutionAlgorithmPlan(
            algorithm=self.name,
            symbol=ctx.symbol,
            side=ctx.side,
            notional=ctx.notional,
            reference_price=round(ctx.reference_price, 4),
            estimated_quantity=quantity_from_notional(ctx.notional, ctx.reference_price),
            legs=legs,
            policy_notes=list(STANDARD_POLICY_NOTES),
        )


def _normalize(profile: tuple[float, ...]) -> list[float]:
    total = sum(max(0.0, w) for w in profile)
    if total <= 0:
        return []
    return [max(0.0, w) / total for w in profile]


def _absorb_remainder(legs: list, target_notional: float, price: float) -> None:
    actual = sum(s.notional for s in legs)
    delta = round(target_notional - actual, 2)
    if delta:
        legs[-1].notional = round(legs[-1].notional + delta, 2)
        legs[-1].estimated_quantity = round(legs[-1].notional / price, 6)
