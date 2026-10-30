"""Pair-spread reversion: trade the spread between two correlated names.

The parent ``symbol`` is the active leg. The hedge leg is described in
parameters (``hedge_symbol``, ``hedge_ratio``, ``hedge_price``). When the
spread (active - hedge×ratio) diverges N sigma from its rolling mean,
enter both legs in opposite directions and unwind at convergence.

Notional is split across the two legs proportional to ``hedge_ratio``;
the broker layer is responsible for routing both as a paired execution.
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


class PairSpreadParams(BaseModel):
    hedge_symbol: str = Field(default="SPY")
    hedge_ratio: float = Field(default=1.0, gt=0, le=10)
    hedge_price: float | None = Field(default=None, gt=0)
    spread_zscore: float = Field(default=2.0, gt=0, le=5)


@register
class PairSpread(ExecutionAlgorithmBase):
    name = "pair_spread"
    category = "mean_reversion"
    description = (
        "Two-leg pair trade entered on spread divergence and unwound on convergence. "
        "Names hedged to roughly market-neutral via the hedge ratio."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = PairSpreadParams(**ctx.parameters)
        active_quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        hedge_price = params.hedge_price or ctx.reference_price
        hedge_notional = round(ctx.notional * params.hedge_ratio, 2)
        hedge_quantity = round(hedge_notional / hedge_price, 6)
        legs = [
            leg(
                "active_leg",
                ctx.side,
                ctx.symbol,
                ctx.notional,
                active_quantity,
                ctx.reference_price,
                parameters={"spread_zscore": params.spread_zscore},
            ),
            leg(
                "hedge_leg",
                opposite_side(ctx.side),
                params.hedge_symbol.strip().upper(),
                hedge_notional,
                hedge_quantity,
                hedge_price,
                parameters={
                    "hedge_ratio": params.hedge_ratio,
                    "spread_zscore": params.spread_zscore,
                },
            ),
        ]
        return ExecutionAlgorithmPlan(
            algorithm=self.name,
            symbol=ctx.symbol,
            side=ctx.side,
            notional=ctx.notional,
            reference_price=round(ctx.reference_price, 4),
            estimated_quantity=active_quantity,
            legs=legs,
            policy_notes=list(STANDARD_POLICY_NOTES)
            + [
                f"Pair trade vs {params.hedge_symbol.strip().upper()} at {params.hedge_ratio}× ratio.",
                "Both legs must fill together; broker layer routes as a paired execution.",
            ],
        )
