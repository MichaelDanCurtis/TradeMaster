"""Bracket order: market entry plus a take-profit and a stop-loss on the opposite side.

Behavior preserved exactly from the legacy implementation. Default take-profit
is +8% (or -8% for sells), default stop-loss is -5% (or +5% for sells). Both
percentages are parameterizable but default to the legacy values so
`test_bracket_algorithm_builds_profit_and_loss_guards` continues to hold.
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


class BracketParams(BaseModel):
    take_profit_percent: float = Field(default=8.0, gt=0, le=100)
    stop_loss_percent: float = Field(default=5.0, gt=0, le=100)


@register
class BracketOrder(ExecutionAlgorithmBase):
    name = "bracket_order"
    category = "microstructure"
    description = (
        "Three-leg bracket: market entry, take-profit limit at +N%, stop-loss at -M%. "
        "The two exits cancel each other (OCO) at the broker."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = BracketParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        tp_multiplier = (
            1 + params.take_profit_percent / 100
            if ctx.side == "buy"
            else 1 - params.take_profit_percent / 100
        )
        sl_multiplier = (
            1 - params.stop_loss_percent / 100
            if ctx.side == "buy"
            else 1 + params.stop_loss_percent / 100
        )
        legs = [
            leg("market_entry", ctx.side, ctx.symbol, ctx.notional, quantity, ctx.reference_price),
            leg(
                "take_profit",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                ctx.reference_price * tp_multiplier,
            ),
            leg(
                "stop_loss",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                ctx.reference_price * sl_multiplier,
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
