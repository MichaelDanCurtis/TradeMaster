"""Sniper: wait for a liquidity event, then send the full size as an IOC.

Sniper algorithms are appropriate for thinly traded names or block-sized
positions where smaller slices would walk the book. The plan describes a
single contingent order — armed with a liquidity-event trigger — plus a
hard cancel window. The broker layer is responsible for monitoring the
trigger and routing the IOC; this algorithm only describes the structure.

Trigger semantics (carried in leg parameters):
- ``min_displayed_size``: book size required before firing
- ``max_price_drift_bps``: maximum allowable drift from the reference at fire time
- ``hard_cancel_seconds``: cancel even if untriggered
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


class SniperParams(BaseModel):
    min_displayed_size: float = Field(default=10_000.0, gt=0)
    max_price_drift_bps: float = Field(default=15.0, ge=0, le=500)
    hard_cancel_seconds: int = Field(default=600, gt=0, le=86_400)


@register
class Sniper(ExecutionAlgorithmBase):
    name = "sniper"
    category = "microstructure"
    description = (
        "Wait for a liquidity event (large displayed size, price within drift band), "
        "then fire an immediate-or-cancel for the full size. Patient liquidity-taker."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = SniperParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        order = leg(
            "armed_ioc",
            ctx.side,
            ctx.symbol,
            ctx.notional,
            quantity,
            price=ctx.reference_price,
            parameters={
                "min_displayed_size": params.min_displayed_size,
                "max_price_drift_bps": params.max_price_drift_bps,
                "hard_cancel_seconds": params.hard_cancel_seconds,
            },
        )
        return ExecutionAlgorithmPlan(
            algorithm=self.name,
            symbol=ctx.symbol,
            side=ctx.side,
            notional=ctx.notional,
            reference_price=round(ctx.reference_price, 4),
            estimated_quantity=quantity,
            legs=[order],
            policy_notes=list(STANDARD_POLICY_NOTES)
            + ["Sniper holds buying power until trigger or hard-cancel."],
        )
