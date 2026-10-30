"""Bridge between the Trader agent's `TraderProposal` and the algorithm registry.

The Trader produces a free-form transaction proposal (`action ∈ {Buy, Hold,
Sell}`, plus optional entry / stop / sizing guidance). The Desk room then
picks an execution algorithm and supplies the concrete notional and
reference price. This module hands the structured proposal off to the
algorithm registry to produce the executable `ExecutionAlgorithmPlan`.

Hold proposals do not produce a plan; the caller treats `None` as
"no trade this round." Buy / sell map to the corresponding algorithm side.

This bridge intentionally does NOT call the BrokerService or modify run
state — it is a pure translation layer. The `BrokerService.preview_order
→ approve → submit` state machine remains the only path that produces
broker orders, and the symbolic constraint engine still gates submission.
"""

from __future__ import annotations

from typing import Any

from tradingagents.agents.schemas import TraderAction, TraderProposal
from tradingagents.algorithms import (
    ExecutionAlgorithmPlan,
    preview,
)


def build_order_plan_from_proposal(
    proposal: TraderProposal,
    *,
    algorithm: str,
    symbol: str,
    notional: float,
    reference_price: float | None = None,
    parameters: dict[str, Any] | None = None,
) -> ExecutionAlgorithmPlan | None:
    """Translate a `TraderProposal` into an `ExecutionAlgorithmPlan`.

    Parameters
    ----------
    proposal:
        The Trader agent's structured proposal.
    algorithm:
        Registered algorithm name (e.g. "twap", "bracket_order"). The
        registry raises `ValueError` on unknown names.
    symbol:
        Instrument symbol; normalized to uppercase by the registry.
    notional:
        Dollar size of the parent order. Must be positive.
    reference_price:
        Quote price at submit time. Defaults to `proposal.entry_price` if
        the Trader supplied one; otherwise required from the caller.
    parameters:
        Algorithm-specific overrides; each algorithm exposes its own
        Pydantic `Params` model with sane defaults.

    Returns
    -------
    ExecutionAlgorithmPlan when the Trader proposed Buy or Sell, otherwise
    `None` (Hold).

    Raises
    ------
    ValueError if `algorithm` is unknown, if `notional` is non-positive,
    or if `reference_price` is missing and the proposal lacks an entry
    price.
    """

    if proposal.action == TraderAction.HOLD:
        return None

    effective_price = reference_price if reference_price is not None else proposal.entry_price
    if effective_price is None:
        raise ValueError(
            "reference_price required: TraderProposal has no entry_price and the caller did not supply one"
        )

    side = "buy" if proposal.action == TraderAction.BUY else "sell"
    return preview(
        algorithm=algorithm,
        symbol=symbol,
        side=side,
        notional=notional,
        reference_price=effective_price,
        parameters=parameters,
    )
