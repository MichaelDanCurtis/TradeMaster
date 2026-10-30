"""Bollinger-band reversion: buy at the lower band, take profit at the midline.

The plan is a limit entry at the lower band (upper for sells), a
take-profit at the midline (MA20 by convention), and a stop beyond the
band by ``stop_band_multiple`` standard deviations. Band values can be
supplied; defaults are computed from the reference price.
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


class BollingerParams(BaseModel):
    midline: float | None = Field(default=None, gt=0)
    upper_band: float | None = Field(default=None, gt=0)
    lower_band: float | None = Field(default=None, gt=0)
    stop_band_multiple: float = Field(default=0.5, gt=0, le=3.0)


@register
class BollingerBand(ExecutionAlgorithmBase):
    name = "bollinger_band"
    category = "mean_reversion"
    description = (
        "Limit entry at the outer band; take profit at the midline; stop beyond the band. "
        "Classical 2-sigma mean reversion."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = BollingerParams(**ctx.parameters)
        midline = params.midline or ctx.reference_price
        upper = params.upper_band or midline * 1.02
        lower = params.lower_band or midline * 0.98
        sigma = (upper - midline) or midline * 0.02
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        if ctx.side == "buy":
            entry_price = lower
            target_price = midline
            stop_price = lower - sigma * params.stop_band_multiple
        else:
            entry_price = upper
            target_price = midline
            stop_price = upper + sigma * params.stop_band_multiple
        legs = [
            leg("limit_entry", ctx.side, ctx.symbol, ctx.notional, quantity, entry_price),
            leg(
                "take_profit",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                target_price,
                parameters={"anchor": "midline"},
            ),
            leg(
                "stop_loss",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                stop_price,
                parameters={"sigma": round(sigma, 4)},
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
            policy_notes=list(STANDARD_POLICY_NOTES),
        )
