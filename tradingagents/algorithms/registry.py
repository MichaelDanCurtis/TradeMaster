"""Algorithm registry: maps a name string to a concrete algorithm class.

Algorithms self-register via the `@register` decorator at import time. The
package `__init__` imports every algorithm module so that
`tradingagents.algorithms.list_algorithms()` returns the full set immediately
after the package is imported, with no further bookkeeping required from
callers.

Lookup is case-insensitive on the algorithm name to keep the API surface
forgiving for human-typed input.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from tradingagents.algorithms.base import (
    AlgorithmContext,
    ExecutionAlgorithmBase,
    ExecutionAlgorithmPlan,
    normalize_side,
    normalize_symbol,
)


_REGISTRY: dict[str, type[ExecutionAlgorithmBase]] = {}


def register(cls: type[ExecutionAlgorithmBase]) -> type[ExecutionAlgorithmBase]:
    """Class decorator that adds an algorithm to the registry.

    The class must define ``name``, ``category``, and ``description`` class
    attributes. ``name`` is stored lowercase for lookup and must be unique
    across the registry.
    """

    if not hasattr(cls, "name") or not isinstance(cls.name, str):
        raise TypeError(f"{cls.__name__} must define a class-level `name: str`")
    key = cls.name.strip().lower()
    if not key:
        raise ValueError(f"{cls.__name__}.name must be non-empty")
    if key in _REGISTRY and _REGISTRY[key] is not cls:
        raise ValueError(f"algorithm name {key!r} is already registered to {_REGISTRY[key].__name__}")
    _REGISTRY[key] = cls
    return cls


def get(name: str) -> ExecutionAlgorithmBase:
    """Return a fresh instance of the algorithm registered under ``name``."""

    key = name.strip().lower()
    cls = _REGISTRY.get(key)
    if cls is None:
        raise ValueError(f"unsupported execution algorithm: {name!r}")
    return cls()


def list_algorithms() -> list[type[ExecutionAlgorithmBase]]:
    """Return all registered algorithm classes, in registration order."""

    return list(_REGISTRY.values())


def list_by_category() -> dict[str, list[type[ExecutionAlgorithmBase]]]:
    """Group registered algorithms by category for catalog rendering."""

    grouped: dict[str, list[type[ExecutionAlgorithmBase]]] = {}
    for cls in _REGISTRY.values():
        grouped.setdefault(cls.category, []).append(cls)
    return grouped


def iter_names() -> Iterator[str]:
    return iter(_REGISTRY.keys())


def preview(
    *,
    algorithm: str,
    symbol: str,
    side: str,
    notional: float,
    reference_price: float,
    parameters: dict[str, Any] | None = None,
) -> ExecutionAlgorithmPlan:
    """High-level entry point: look up the algorithm, validate, and propose.

    Validates the universal inputs (symbol, side, notional, reference_price)
    here so that individual algorithms can assume normalized values. The
    legacy `ui.execution_algorithms.preview_execution_algorithm` delegates
    to this function.
    """

    if notional <= 0:
        raise ValueError("notional must be greater than zero")
    if reference_price <= 0:
        raise ValueError("reference_price must be greater than zero")

    impl = get(algorithm)
    ctx = AlgorithmContext(
        symbol=normalize_symbol(symbol),
        side=normalize_side(side),
        notional=notional,
        reference_price=reference_price,
        parameters=parameters or {},
    )
    return impl.propose(ctx)
