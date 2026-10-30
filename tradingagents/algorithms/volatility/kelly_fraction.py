"""Kelly fraction: size = fractional Kelly given an edge / odds estimate.

For a binary bet with win probability p and win/loss ratio b, full Kelly
is (p(b+1) - 1) / b. Most practitioners use a fraction of that
(``kelly_fraction``, default 0.5) for stability. The plan caps the
notional at the parent's requested size and falls back to zero if the
Kelly estimate is non-positive.

Inputs (via parameters):
- ``win_probability``: estimated win probability ∈ (0, 1)
- ``win_loss_ratio``: average win / average loss (default 1.5)
- ``kelly_fraction``: scaling on full Kelly (default 0.5 = half-Kelly)
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


class KellyParams(BaseModel):
    win_probability: float = Field(default=0.55, gt=0, lt=1)
    win_loss_ratio: float = Field(default=1.5, gt=0, le=20)
    kelly_fraction: float = Field(default=0.5, gt=0, le=1.0)


@register
class KellyFraction(ExecutionAlgorithmBase):
    name = "kelly_fraction"
    category = "volatility"
    description = (
        "Size by fractional Kelly given an estimated edge. "
        "Refuses to size up when the edge estimate is non-positive."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = KellyParams(**ctx.parameters)
        full_kelly = (
            params.win_probability * (params.win_loss_ratio + 1) - 1
        ) / params.win_loss_ratio
        fractional = max(0.0, full_kelly * params.kelly_fraction)
        scale = min(1.0, fractional)
        notional = round(ctx.notional * scale, 2)
        quantity = round(notional / ctx.reference_price, 6) if notional > 0 else 0.0
        legs: list = []
        notes = list(STANDARD_POLICY_NOTES)
        if notional > 0:
            legs.append(
                leg(
                    "market_entry",
                    ctx.side,
                    ctx.symbol,
                    notional,
                    quantity,
                    ctx.reference_price,
                    parameters={
                        "full_kelly": round(full_kelly, 4),
                        "fractional_kelly": round(fractional, 4),
                        "kelly_fraction": params.kelly_fraction,
                    },
                )
            )
            notes.append(
                f"Kelly: full={round(full_kelly, 3)}, applied={round(fractional, 3)}."
            )
        else:
            notes.append("Kelly estimate is non-positive; no entry proposed.")
        return ExecutionAlgorithmPlan(
            algorithm=self.name,
            symbol=ctx.symbol,
            side=ctx.side,
            notional=notional,
            reference_price=round(ctx.reference_price, 4),
            estimated_quantity=quantity,
            legs=legs,
            policy_notes=notes,
        )
