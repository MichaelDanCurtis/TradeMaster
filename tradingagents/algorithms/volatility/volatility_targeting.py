"""Volatility targeting: scale notional by target_vol / realized_vol.

If the position vol is higher than target, downscale; if lower, upscale
(bounded by the parent notional cap and an upper-scale ceiling). Useful
when you want a roughly constant portfolio-vol contribution per name
regardless of which name you're trading today.

Inputs (via parameters):
- ``realized_vol_percent``: recent realized vol of the name (annualized %)
- ``target_vol_percent``: desired annualized vol contribution (default 15%)
- ``max_scale``: ceiling on the upscale (default 2.0)
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tradingagents.algorithms.base import (
    STANDARD_POLICY_NOTES,
    AlgorithmContext,
    ExecutionAlgorithmBase,
    ExecutionAlgorithmPlan,
    leg,
)
from tradingagents.algorithms.registry import register


class VolTargetParams(BaseModel):
    realized_vol_percent: float | None = Field(default=None, gt=0, le=500)
    target_vol_percent: float = Field(default=15.0, gt=0, le=200)
    max_scale: float = Field(default=2.0, gt=0, le=5.0)


@register
class VolatilityTargeting(ExecutionAlgorithmBase):
    name = "volatility_targeting"
    category = "volatility"
    description = (
        "Scale notional by target_vol / realized_vol so each position contributes "
        "a roughly constant amount of portfolio volatility."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = VolTargetParams(**ctx.parameters)
        realized = params.realized_vol_percent or params.target_vol_percent
        scale = min(params.max_scale, params.target_vol_percent / realized)
        notional = round(ctx.notional * scale, 2)
        quantity = round(notional / ctx.reference_price, 6)
        legs = [
            leg(
                "market_entry",
                ctx.side,
                ctx.symbol,
                notional,
                quantity,
                ctx.reference_price,
                parameters={
                    "realized_vol_percent": round(realized, 4),
                    "target_vol_percent": params.target_vol_percent,
                    "scale": round(scale, 4),
                },
            )
        ]
        return ExecutionAlgorithmPlan(
            algorithm=self.name,
            symbol=ctx.symbol,
            side=ctx.side,
            notional=notional,
            reference_price=round(ctx.reference_price, 4),
            estimated_quantity=quantity,
            legs=legs,
            policy_notes=list(STANDARD_POLICY_NOTES)
            + [f"Vol-targeted scale: {round(scale, 3)}× requested notional."],
        )
