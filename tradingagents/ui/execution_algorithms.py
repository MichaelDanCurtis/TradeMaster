"""Legacy execution-algorithm façade.

The original single-dispatch implementation lived here. As of the 2026-05
inventory pass, the catalogue grew to 27 algorithms organized into six
categories under ``tradingagents.algorithms``. This module is preserved
as a back-compat surface: callers of ``preview_execution_algorithm`` and
type users of ``ExecutionAlgorithmLeg`` / ``ExecutionAlgorithmPlan``
continue to work without changes.

The ``ExecutionAlgorithm`` type alias is widened from the original
three-name Literal to ``str`` to admit the broader catalogue. The
registry validates the name at lookup time and raises a ``ValueError``
matching the legacy error message on unknown algorithms.
"""

from __future__ import annotations

from typing import Any

from tradingagents.algorithms import preview as _registry_preview
from tradingagents.algorithms.base import (
    ExecutionAlgorithmLeg,
    ExecutionAlgorithmPlan,
    ExecutionSide,
)


# ``ExecutionAlgorithm`` was originally a 3-name Literal. It is now ``str``
# because the catalogue spans 27 algorithms (see docs/ALGORITHM_LIBRARY.md).
# The registry rejects unknown names at lookup, so the runtime contract is
# unchanged for callers who still pass the legacy names.
ExecutionAlgorithm = str


__all__ = [
    "ExecutionAlgorithm",
    "ExecutionAlgorithmLeg",
    "ExecutionAlgorithmPlan",
    "ExecutionSide",
    "preview_execution_algorithm",
]


def preview_execution_algorithm(
    *,
    algorithm: str,
    symbol: str,
    side: str,
    notional: float,
    reference_price: float,
    parameters: dict[str, Any] | None = None,
) -> ExecutionAlgorithmPlan:
    """Look up ``algorithm`` in the registry and produce its preview plan.

    Signature preserved bit-for-bit from the original implementation
    (``parameters`` is a new optional keyword that defaults to None, so
    existing positional or keyword call-sites continue to work).
    """

    return _registry_preview(
        algorithm=algorithm,
        symbol=symbol,
        side=side,
        notional=notional,
        reference_price=reference_price,
        parameters=parameters,
    )
