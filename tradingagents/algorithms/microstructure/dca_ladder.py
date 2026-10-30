"""DCA ladder: split the notional across N price rungs spaced from the reference.

For buys the ladder steps DOWN below the reference (you accumulate on
weakness); for sells it steps UP. The default schedule matches the legacy
implementation exactly so the existing
`test_dca_ladder_algorithm_splits_notional_across_ladder_prices` test holds:

    buy:  [1.00, 0.97, 0.94, 0.90]   (4 rungs, total -10% from reference)
    sell: [1.00, 1.03, 1.06, 1.10]

Any rounding remainder is absorbed by the last leg so the notional sum is
preserved bit-exactly.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tradingagents.algorithms.base import (
    STANDARD_POLICY_NOTES,
    ExecutionAlgorithmLeg,
    AlgorithmContext,
    ExecutionAlgorithmBase,
    ExecutionAlgorithmPlan,
    quantity_from_notional,
)
from tradingagents.algorithms.registry import register


class LadderParams(BaseModel):
    rungs: int = Field(default=4, ge=2, le=12)
    span_percent: float = Field(default=10.0, gt=0, le=50)


@register
class DCALadder(ExecutionAlgorithmBase):
    name = "dca_ladder"
    category = "microstructure"
    description = (
        "Dollar-cost-average across N price rungs spaced toward the unfavorable "
        "side of the reference price. Patient entry that improves average cost "
        "on adverse moves."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = LadderParams(**ctx.parameters)
        ladder_prices = _ladder_prices(
            ctx.reference_price,
            ctx.side,
            params.rungs,
            params.span_percent,
        )
        leg_notional = round(ctx.notional / len(ladder_prices), 2)
        legs: list[ExecutionAlgorithmLeg] = [
            ExecutionAlgorithmLeg(
                kind="ladder_entry",
                side=ctx.side,
                symbol=ctx.symbol,
                notional=leg_notional,
                estimated_quantity=round(leg_notional / price, 6),
                price=price,
            )
            for price in ladder_prices
        ]
        remainder = round(ctx.notional - sum(leg.notional for leg in legs), 2)
        if remainder:
            legs[-1].notional = round(legs[-1].notional + remainder, 2)
            assert legs[-1].price is not None
            legs[-1].estimated_quantity = round(legs[-1].notional / legs[-1].price, 6)
        quantity = quantity_from_notional(ctx.notional, ctx.reference_price)
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


def _ladder_prices(
    reference_price: float,
    side: str,
    rungs: int,
    span_percent: float,
) -> list[float]:
    """Rung prices spaced from the reference toward the unfavorable side.

    For the default (rungs=4, span_percent=10) the legacy schedule is
    preserved exactly: buy = [1.00, 0.97, 0.94, 0.90], sell = [1.00, 1.03,
    1.06, 1.10]. The legacy schedule is intentionally non-uniform (3% steps
    for the first three rungs, then a larger 4% step to the floor) which
    front-weights the cheaper averaging exposure.

    For non-default rung counts or spans, falls back to uniform spacing
    across the full span.
    """

    if rungs == 4 and span_percent == 10.0:
        legacy = [1.0, 0.97, 0.94, 0.90] if side == "buy" else [1.0, 1.03, 1.06, 1.10]
        return [round(reference_price * m, 4) for m in legacy]

    step = span_percent / (rungs - 1) / 100
    multipliers: list[float] = []
    for i in range(rungs):
        delta = step * i
        if side == "buy":
            multipliers.append(1 - delta)
        else:
            multipliers.append(1 + delta)
    return [round(reference_price * m, 4) for m in multipliers]
