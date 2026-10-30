"""CPPI: Constant Proportion Portfolio Insurance — size by cushion × multiplier.

CPPI keeps a floor under portfolio value by limiting risky-asset exposure
to ``multiplier × cushion``, where cushion = portfolio_value − floor.
This algorithm uses that formula to size a single name's entry, treating
the parent ``notional`` as the cap.

Inputs (via parameters):
- ``portfolio_value``: total account equity (required for meaningful sizing)
- ``floor_value``: protected floor below which exposure goes to zero
- ``multiplier``: typically 3–5; controls how aggressively the cushion is leveraged
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


class CPPIParams(BaseModel):
    portfolio_value: float | None = Field(default=None, gt=0)
    floor_value: float | None = Field(default=None, ge=0)
    multiplier: float = Field(default=3.0, gt=0, le=10)


@register
class CPPI(ExecutionAlgorithmBase):
    name = "cppi"
    category = "volatility"
    description = (
        "Constant Proportion Portfolio Insurance. Risky-asset exposure capped at "
        "multiplier × (portfolio_value − floor). Goes to zero when cushion is zero."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = CPPIParams(**ctx.parameters)
        portfolio_value = params.portfolio_value or ctx.notional * 10
        floor_value = params.floor_value if params.floor_value is not None else portfolio_value * 0.9
        if floor_value >= portfolio_value:
            cushion = 0.0
        else:
            cushion = portfolio_value - floor_value
        cppi_exposure = cushion * params.multiplier
        notional = round(min(ctx.notional, max(0.0, cppi_exposure)), 2)
        quantity = round(notional / ctx.reference_price, 6) if notional > 0 else 0.0
        legs: list = []
        notes = list(STANDARD_POLICY_NOTES) + [
            f"CPPI exposure cap: ${round(cppi_exposure, 2)} (cushion ${round(cushion, 2)} × {params.multiplier})."
        ]
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
                        "portfolio_value": round(portfolio_value, 2),
                        "floor_value": round(floor_value, 2),
                        "multiplier": params.multiplier,
                        "cushion": round(cushion, 2),
                    },
                )
            )
        else:
            notes.append("Cushion is zero or negative; CPPI prohibits any new exposure.")
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
