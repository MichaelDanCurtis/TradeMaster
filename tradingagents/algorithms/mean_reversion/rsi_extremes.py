"""RSI extremes: buy oversold, sell overbought, exit at midline.

Assumes the upstream agent reports a current RSI value. Defaults: buy
when RSI<30, sell when RSI>70, exit at RSI~50 (midline). The plan is a
market entry plus a fixed-percent take-profit and stop, on the
assumption that the indicator-triggered position is short-horizon.
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


class RSIParams(BaseModel):
    current_rsi: float | None = Field(default=None, ge=0, le=100)
    take_profit_percent: float = Field(default=2.0, gt=0, le=20)
    stop_percent: float = Field(default=3.0, gt=0, le=20)


@register
class RSIExtremes(ExecutionAlgorithmBase):
    name = "rsi_extremes"
    category = "mean_reversion"
    description = (
        "Counter-trend entry when RSI is at an extreme. Take profit toward midline; "
        "stop if the extreme deepens."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = RSIParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        tp_mul = (
            1 + params.take_profit_percent / 100
            if ctx.side == "buy"
            else 1 - params.take_profit_percent / 100
        )
        sl_mul = (
            1 - params.stop_percent / 100
            if ctx.side == "buy"
            else 1 + params.stop_percent / 100
        )
        rsi_param = (
            {"current_rsi": params.current_rsi} if params.current_rsi is not None else {}
        )
        legs = [
            leg(
                "market_entry",
                ctx.side,
                ctx.symbol,
                ctx.notional,
                quantity,
                ctx.reference_price,
                parameters=rsi_param,
            ),
            leg(
                "take_profit",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                ctx.reference_price * tp_mul,
            ),
            leg(
                "stop_loss",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                ctx.reference_price * sl_mul,
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
