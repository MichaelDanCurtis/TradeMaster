"""Execution algorithm base types.

This module owns the data contracts (`ExecutionAlgorithmLeg`,
`ExecutionAlgorithmPlan`) and the interface (`ExecutionAlgorithmBase`,
`AlgorithmContext`) that every concrete execution algorithm implements.

The legacy single-dispatch entry point lives at
`tradingagents.ui.execution_algorithms.preview_execution_algorithm`; that
function now delegates to the registry defined in
`tradingagents.algorithms.registry`. The legacy module continues to re-export
`ExecutionAlgorithmLeg` and `ExecutionAlgorithmPlan` so callers keep working.

Determinism guarantee: every algorithm in this library is a pure function of
its `AlgorithmContext`. The same context produces the same plan, regardless of
clock time, randomness, or external state. Tests rely on this.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field


ExecutionSide = Literal["buy", "sell"]


class ExecutionAlgorithmLeg(BaseModel):
    """A single child order or contingent leg produced by an algorithm.

    Multiple legs may be siblings (parallel time-slices) or sequential
    (entry → take-profit → stop-loss bracket). The interpretation depends on
    the parent algorithm; the `kind` field documents which.
    """

    kind: str
    side: ExecutionSide
    symbol: str
    notional: float
    estimated_quantity: float
    price: float | None = None
    parameters: dict[str, float | str] = Field(default_factory=dict)


class ExecutionAlgorithmPlan(BaseModel):
    """The full plan produced by an algorithm.

    Contains the original intent (symbol, side, notional, reference_price), a
    derived top-level `estimated_quantity`, and the concrete child legs that
    realize the strategy. `policy_notes` is a human-readable channel for
    paper-mode and symbolic-engine reminders; broker submission must still go
    through the `BrokerService` state machine.
    """

    algorithm: str
    symbol: str
    side: ExecutionSide
    notional: float
    reference_price: float
    estimated_quantity: float
    legs: list[ExecutionAlgorithmLeg]
    policy_notes: list[str]


class AlgorithmContext(BaseModel):
    """Input bundle for `ExecutionAlgorithmBase.propose`.

    `parameters` is the open-ended escape hatch for algorithms that need extra
    inputs (window length, indicator readings, account equity, volatility,
    edge estimates, etc.). Each algorithm exposes a `Params` model that picks
    the keys it needs and applies sensible defaults; algorithms must NEVER
    raise on missing optional keys — they must degrade to a documented default.
    """

    symbol: str
    side: ExecutionSide
    notional: float
    reference_price: float
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExecutionAlgorithmBase:
    """Base class for execution algorithms.

    Subclasses set the three class-level attributes and implement
    `propose(ctx)`. Registration is via the `@register` decorator from
    `tradingagents.algorithms.registry`.

    Subclasses MUST be deterministic: no clock reads, no randomness, no
    network I/O. The runtime supplies any time- or market-dependent inputs
    through `ctx.parameters`.
    """

    name: ClassVar[str]
    category: ClassVar[str]
    description: ClassVar[str]

    def propose(self, ctx: AlgorithmContext) -> ExecutionAlgorithmPlan:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Helpers used across algorithms
# ---------------------------------------------------------------------------


def normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("symbol must not be empty")
    return normalized


def normalize_side(side: str) -> ExecutionSide:
    normalized = side.strip().lower()
    if normalized not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    return normalized  # type: ignore[return-value]


def opposite_side(side: ExecutionSide) -> ExecutionSide:
    return "sell" if side == "buy" else "buy"


def quantity_from_notional(notional: float, price: float) -> float:
    if price <= 0:
        raise ValueError("price must be positive")
    return round(notional / price, 6)


def leg(
    kind: str,
    side: ExecutionSide,
    symbol: str,
    notional: float,
    quantity: float,
    price: float | None = None,
    parameters: dict[str, float | str] | None = None,
) -> ExecutionAlgorithmLeg:
    return ExecutionAlgorithmLeg(
        kind=kind,
        side=side,
        symbol=symbol,
        notional=round(notional, 2),
        estimated_quantity=round(quantity, 6),
        price=round(price, 4) if price is not None else None,
        parameters=parameters or {},
    )


STANDARD_POLICY_NOTES: list[str] = [
    "Paper preview only until human approval.",
    "Symbolic constraint engine must pass before broker submission.",
]
