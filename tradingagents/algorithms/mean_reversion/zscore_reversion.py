"""Z-score reversion: enter on a 2-sigma deviation; target z=0; stop at z=3.

Computes target / stop prices from a recent mean and standard deviation
(both supplied via parameters; defaults are computed from the reference
price). Enters at the current price assuming it represents the
``current_zscore`` deviation.
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


class ZScoreParams(BaseModel):
    rolling_mean: float | None = Field(default=None, gt=0)
    rolling_stdev: float | None = Field(default=None, gt=0)
    entry_zscore: float = Field(default=2.0, gt=0, le=4)
    stop_zscore: float = Field(default=3.0, gt=0, le=5)


@register
class ZScoreReversion(ExecutionAlgorithmBase):
    name = "zscore_reversion"
    category = "mean_reversion"
    description = (
        "Statistical mean reversion. Enter at N-sigma deviation, target the mean, "
        "stop at the next sigma."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = ZScoreParams(**ctx.parameters)
        rolling_mean = params.rolling_mean or ctx.reference_price * 1.02
        rolling_stdev = params.rolling_stdev or ctx.reference_price * 0.01
        if params.stop_zscore <= params.entry_zscore:
            raise ValueError("stop_zscore must exceed entry_zscore")
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
        if ctx.side == "buy":
            stop_price = rolling_mean - rolling_stdev * params.stop_zscore
        else:
            stop_price = rolling_mean + rolling_stdev * params.stop_zscore
        legs = [
            leg(
                "market_entry",
                ctx.side,
                ctx.symbol,
                ctx.notional,
                quantity,
                ctx.reference_price,
                parameters={
                    "rolling_mean": round(rolling_mean, 4),
                    "rolling_stdev": round(rolling_stdev, 4),
                    "entry_zscore": params.entry_zscore,
                },
            ),
            leg(
                "take_profit",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                rolling_mean,
                parameters={"target_zscore": 0.0},
            ),
            leg(
                "stop_loss",
                opposite_side(ctx.side),
                ctx.symbol,
                ctx.notional,
                quantity,
                stop_price,
                parameters={"stop_zscore": params.stop_zscore},
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
