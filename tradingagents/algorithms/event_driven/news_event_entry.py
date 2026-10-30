"""News-event entry: enter only on volume-confirmed reaction.

A news headline alone is not a trade signal — most fade. This algorithm
arms a stop-entry that only fires when (a) price moves favorably by
``trigger_percent`` AND (b) volume in the trigger window meets
``min_volume_multiple`` × the recent average. The broker layer enforces
the dual condition.

Inputs (via parameters):
- ``sentiment_score``: 0..1 confidence in direction (default 0.7)
- ``trigger_percent``: minimum directional move to fire (default 0.8%)
- ``min_volume_multiple``: required volume vs average (default 1.5×)
- ``stop_percent``: stop distance after fill (default 2%)
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


class NewsEventParams(BaseModel):
    sentiment_score: float = Field(default=0.7, ge=0, le=1)
    trigger_percent: float = Field(default=0.8, gt=0, le=20)
    min_volume_multiple: float = Field(default=1.5, gt=0, le=20)
    stop_percent: float = Field(default=2.0, gt=0, le=10)


@register
class NewsEventEntry(ExecutionAlgorithmBase):
    name = "news_event_entry"
    category = "event_driven"
    description = (
        "Volume-confirmed directional reaction to a news event. "
        "Fires only when price AND volume both confirm; ignores low-conviction headlines."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = NewsEventParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        if ctx.side == "buy":
            trigger_price = ctx.reference_price * (1 + params.trigger_percent / 100)
            stop_price = ctx.reference_price * (1 - params.stop_percent / 100)
        else:
            trigger_price = ctx.reference_price * (1 - params.trigger_percent / 100)
            stop_price = ctx.reference_price * (1 + params.stop_percent / 100)
        legs = [
            leg(
                "armed_entry",
                ctx.side,
                ctx.symbol,
                ctx.notional,
                quantity,
                trigger_price,
                parameters={
                    "sentiment_score": params.sentiment_score,
                    "trigger_kind": "stop_with_volume_confirm",
                    "min_volume_multiple": params.min_volume_multiple,
                },
            ),
            leg(
                "stop_loss",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                stop_price,
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
            policy_notes=list(STANDARD_POLICY_NOTES)
            + [
                f"Fires only on volume ≥ {params.min_volume_multiple}× average AND price move ≥ {params.trigger_percent}%.",
            ],
        )
