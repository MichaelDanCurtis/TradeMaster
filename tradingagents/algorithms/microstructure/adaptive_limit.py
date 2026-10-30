"""Adaptive limit: aggressive limit peg with a timeout fallback to market.

Submits a limit just inside the bid-ask spread (a few basis points behind
the touch for buys, ahead for sells). If unfilled after a configurable
timeout the residual is converted to a market order. This is the
"price-improving but bounded-risk" execution style used for medium-urgency
fills.

The leg structure exposes two child orders: the initial limit and the
fallback market. The broker layer is responsible for cancelling the limit
when the timeout elapses; this algorithm only describes the plan.
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


class AdaptiveLimitParams(BaseModel):
    spread_bps: float = Field(default=3.0, ge=0, le=200)
    timeout_seconds: int = Field(default=120, gt=0, le=3600)


@register
class AdaptiveLimit(ExecutionAlgorithmBase):
    name = "adaptive_limit"
    category = "microstructure"
    description = (
        "Price-improving limit just inside the touch with a timeout fallback to market. "
        "Captures spread when liquidity is friendly; gives up bps for certainty when not."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = AdaptiveLimitParams(**ctx.parameters)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        offset = ctx.reference_price * params.spread_bps / 10_000
        limit_price = (
            ctx.reference_price - offset if ctx.side == "buy" else ctx.reference_price + offset
        )
        legs = [
            leg(
                "limit_peg",
                ctx.side,
                ctx.symbol,
                ctx.notional,
                quantity,
                price=limit_price,
                parameters={"timeout_seconds": params.timeout_seconds},
            ),
            leg(
                "market_fallback",
                ctx.side,
                ctx.symbol,
                ctx.notional,
                quantity,
                price=ctx.reference_price,
                parameters={"trigger": "limit_timeout"},
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
