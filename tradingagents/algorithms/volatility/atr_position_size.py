"""ATR-based position sizing: stop = N×ATR; size = risk_budget / (N×ATR).

Rather than sizing to a fixed notional, this algorithm sizes the position
so that the ATR-based stop equals a fixed dollar risk. The caller passes
the parent notional as a *cap*; if the ATR-implied size would exceed it,
the cap is used and risk-per-trade is correspondingly lower.

Inputs (via parameters):
- ``atr``: average true range in price units
- ``risk_budget_notional``: dollar risk on the trade
- ``atr_multiple``: stop distance in ATR units (default 2)

If ``atr`` is missing, falls back to 1% of the reference price.
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
)
from tradingagents.algorithms.registry import register


class ATRSizeParams(BaseModel):
    atr: float | None = Field(default=None, gt=0)
    risk_budget_notional: float = Field(default=500.0, gt=0)
    atr_multiple: float = Field(default=2.0, gt=0, le=10)


@register
class ATRPositionSize(ExecutionAlgorithmBase):
    name = "atr_position_size"
    category = "volatility"
    description = (
        "Size the position so the ATR-based stop equals a fixed dollar risk. "
        "Equalizes risk-per-trade across names with different volatility."
    )

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        params = ATRSizeParams(**ctx.parameters)
        atr = params.atr or ctx.reference_price * 0.01
        risk_per_share = atr * params.atr_multiple
        if risk_per_share <= 0:
            raise ValueError("risk per share must be positive")
        risk_implied_quantity = params.risk_budget_notional / risk_per_share
        cap_quantity = ctx.notional / ctx.reference_price
        quantity = round(min(risk_implied_quantity, cap_quantity), 6)
        notional = round(quantity * ctx.reference_price, 2)
        stop_price = (
            ctx.reference_price - risk_per_share
            if ctx.side == "buy"
            else ctx.reference_price + risk_per_share
        )
        legs = [
            leg(
                "market_entry",
                ctx.side,
                ctx.symbol,
                notional,
                quantity,
                ctx.reference_price,
                parameters={
                    "atr": round(atr, 4),
                    "atr_multiple": params.atr_multiple,
                    "risk_per_share": round(risk_per_share, 4),
                    "risk_budget_notional": params.risk_budget_notional,
                },
            ),
            leg(
                "atr_stop",
                opposite_side(ctx.side),
                ctx.symbol,
                notional,
                quantity,
                stop_price,
            ),
        ]
        notes = list(STANDARD_POLICY_NOTES)
        if risk_implied_quantity > cap_quantity:
            notes.append(
                "ATR sizing exceeded notional cap; cap binding, realized risk is below budget."
            )
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
