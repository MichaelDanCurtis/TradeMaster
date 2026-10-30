"""Implementation Shortfall: front-loaded schedule that minimizes arrival-price drift.

Almgren-Chriss-inspired: the optimal schedule under quadratic temporary
impact and linear permanent impact is an exponential decay weighted by
risk aversion. We expose a single parameter ``aggressiveness`` ∈ (0, 1]
that controls how front-loaded the schedule is — 1.0 is heavily
front-loaded, 0.1 approaches uniform (TWAP-like).

This is the right choice when you're trading on a thesis that the market
is about to figure out (so arrival-price slippage dominates impact cost).
"""

from __future__ import annotations

import math

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


class ISParams(BaseModel):
    window_minutes: int = Field(default=30, gt=0, le=390)
    slices: int = Field(default=10, ge=2, le=120)
    aggressiveness: float = Field(default=0.6, gt=0, le=1.0)


@register
class ImplementationShortfall(ExecutionAlgorithmBase):
    name = "implementation_shortfall"
    category = "time_based"
    description = (
        "Front-loaded schedule that minimizes arrival-price slippage. "
        "Higher aggressiveness shifts more notional into the earliest slices."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = ISParams(**ctx.parameters)
        weights = _front_loaded_weights(params.slices, params.aggressiveness)
        slice_seconds = round(params.window_minutes * 60 / params.slices)
        legs = []
        for i, w in enumerate(weights):
            slice_notional = round(ctx.notional * w, 2)
            slice_quantity = round(slice_notional / ctx.reference_price, 6)
            legs.append(
                leg(
                    "is_slice",
                    ctx.side,
                    ctx.symbol,
                    slice_notional,
                    slice_quantity,
                    price=ctx.reference_price,
                    parameters={
                        "offset_seconds": i * slice_seconds,
                        "weight": round(w, 4),
                        "slice_index": i,
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
            policy_notes=list(STANDARD_POLICY_NOTES)
            + [f"Implementation Shortfall: aggressiveness={params.aggressiveness}"],
        )


def _front_loaded_weights(slices: int, aggressiveness: float) -> list[float]:
    """Normalized exponentially-decaying weights.

    decay = aggressiveness * 5  → tau spans the window. At aggressiveness=1
    the first slice carries roughly e^0 / (e^0 + e^-1 + e^-2 + …) of the
    total. Decay rate is clamped to keep the smallest weight positive.
    """

    decay = max(0.05, aggressiveness * 5.0) / slices
    raw = [math.exp(-decay * i) for i in range(slices)]
    total = sum(raw)
    return [w / total for w in raw]


def _absorb_remainder(legs: list, target_notional: float, price: float) -> None:
    actual = sum(s.notional for s in legs)
    delta = round(target_notional - actual, 2)
    if delta:
        legs[-1].notional = round(legs[-1].notional + delta, 2)
        legs[-1].estimated_quantity = round(legs[-1].notional / price, 6)
