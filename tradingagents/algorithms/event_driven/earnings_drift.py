"""Post-earnings drift: enter the day after a guidance beat; ride for N days.

Empirical pattern: stocks that beat earnings AND raise guidance tend to
drift in the direction of the beat for 30–60 days post-release. This
algorithm enters at market on the day after the release (caller times the
submit) and exits at a target multiple of the surprise, with a stop just
below the pre-release price.

Inputs (via parameters):
- ``surprise_percent``: signed earnings surprise (default 5%)
- ``guidance_raised``: bool, true if forward guidance was raised (default True)
- ``hold_days``: planned hold horizon (default 45)
- ``stop_at_pre_release_price``: anchor stop at this price (default reference × 0.97)
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


class EarningsDriftParams(BaseModel):
    surprise_percent: float = Field(default=5.0, gt=-100, le=100)
    guidance_raised: bool = Field(default=True)
    hold_days: int = Field(default=45, ge=1, le=180)
    stop_at_pre_release_price: float | None = Field(default=None, gt=0)


@register
class EarningsDrift(ExecutionAlgorithmBase):
    name = "earnings_drift"
    category = "event_driven"
    description = (
        "Post-earnings drift: enter the day after a guidance beat, ride for ~45 days. "
        "Refuses to size up if the surprise is non-positive or guidance was not raised."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = EarningsDriftParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        gating_failed = params.surprise_percent <= 0 or not params.guidance_raised
        target_multiplier = 1 + 3 * params.surprise_percent / 100
        target_price = ctx.reference_price * target_multiplier
        stop_price = params.stop_at_pre_release_price or ctx.reference_price * 0.97
        legs: list = []
        notes = list(STANDARD_POLICY_NOTES) + [f"Planned hold: {params.hold_days} days."]
        if gating_failed:
            notes.append(
                "Gate failed: requires positive surprise AND raised guidance; no entry proposed."
            )
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
                            "surprise_percent": params.surprise_percent,
                            "guidance_raised": str(params.guidance_raised),
                            "hold_days": params.hold_days,
                        },
                    ),
                    leg(
                        "take_profit",
                        opposite_side(ctx.side),
                        ctx.symbol,
                        ctx.notional,
                        quantity,
                        target_price,
                        parameters={"anchor": "drift_target"},
                    ),
                    leg(
                        "stop_loss",
                        opposite_side(ctx.side),
                        ctx.symbol,
                        ctx.notional,
                        quantity,
                        stop_price,
                        parameters={"anchor": "pre_release_price"},
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
