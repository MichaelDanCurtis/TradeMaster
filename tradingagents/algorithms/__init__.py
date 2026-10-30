"""Execution algorithm library.

Importing this package registers every concrete algorithm with the central
registry. The public entry points are:

- ``preview(...)``: name → ExecutionAlgorithmPlan dispatch (used by the
  legacy ``ui.execution_algorithms.preview_execution_algorithm`` façade)
- ``list_algorithms()`` / ``list_by_category()``: catalogue inspection
- ``ExecutionAlgorithmPlan`` / ``ExecutionAlgorithmLeg`` / ``AlgorithmContext``:
  the data contracts

Catalogue: see ``docs/ALGORITHM_LIBRARY.md`` for the full list with
descriptions, parameters, and intended use.
"""

from __future__ import annotations

from tradingagents.algorithms.base import (
    AlgorithmContext,
    ExecutionAlgorithmBase,
    ExecutionAlgorithmLeg,
    ExecutionAlgorithmPlan,
    ExecutionSide,
)

# Side-effect imports — each subpackage registers its algorithms on import.
from tradingagents.algorithms import (  # noqa: F401  (import for side-effect)
    event_driven,
    mean_reversion,
    microstructure,
    momentum,
    time_based,
    volatility,
)
from tradingagents.algorithms.registry import (
    get,
    iter_names,
    list_algorithms,
    list_by_category,
    preview,
    register,
)

__all__ = [
    "AlgorithmContext",
    "ExecutionAlgorithmBase",
    "ExecutionAlgorithmLeg",
    "ExecutionAlgorithmPlan",
    "ExecutionSide",
    "get",
    "iter_names",
    "list_algorithms",
    "list_by_category",
    "preview",
    "register",
]
