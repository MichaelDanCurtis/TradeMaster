"""Registry-level tests: catalogue, registration, dispatch, and back-compat.

These exercise the public surface of `tradingagents.algorithms` without
asserting on the internal plan shape of any single algorithm — those live
in `test_smoke_all_algorithms.py`.
"""

from __future__ import annotations

import pytest

from tradingagents.algorithms import (
    ExecutionAlgorithmPlan,
    list_algorithms,
    list_by_category,
    preview,
)


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


EXPECTED_CATEGORIES = {
    "microstructure",
    "time_based",
    "momentum",
    "mean_reversion",
    "volatility",
    "event_driven",
}


def test_registry_has_at_least_20_algorithms():
    """User explicitly requested >= 20 algorithms in the overnight brief."""

    assert len(list_algorithms()) >= 20


def test_registry_covers_every_expected_category():
    grouped = list_by_category()
    assert set(grouped.keys()) == EXPECTED_CATEGORIES
    for category, items in grouped.items():
        assert items, f"category {category} has no algorithms"


def test_registry_names_are_unique():
    names = [cls.name for cls in list_algorithms()]
    assert len(names) == len(set(names))


def test_every_algorithm_class_has_required_metadata():
    for cls in list_algorithms():
        assert isinstance(cls.name, str) and cls.name
        assert isinstance(cls.category, str) and cls.category
        assert isinstance(cls.description, str) and cls.description


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_preview_rejects_unknown_algorithm():
    with pytest.raises(ValueError, match="unsupported execution algorithm"):
        preview(
            algorithm="moonshot",
            symbol="NVDA",
            side="buy",
            notional=1000,
            reference_price=200,
        )


def test_preview_rejects_non_positive_notional():
    with pytest.raises(ValueError, match="notional"):
        preview(
            algorithm="trailing_stop",
            symbol="NVDA",
            side="buy",
            notional=0,
            reference_price=200,
        )


def test_preview_rejects_non_positive_reference_price():
    with pytest.raises(ValueError, match="reference_price"):
        preview(
            algorithm="trailing_stop",
            symbol="NVDA",
            side="buy",
            notional=1000,
            reference_price=0,
        )


def test_preview_normalizes_symbol_to_uppercase():
    plan = preview(
        algorithm="trailing_stop",
        symbol="  nvda  ",
        side="buy",
        notional=1000,
        reference_price=200,
    )
    assert plan.symbol == "NVDA"


def test_preview_normalizes_side_to_lowercase():
    plan = preview(
        algorithm="trailing_stop",
        symbol="NVDA",
        side="BUY",
        notional=1000,
        reference_price=200,
    )
    assert plan.side == "buy"


# ---------------------------------------------------------------------------
# Back-compat: legacy façade entry point
# ---------------------------------------------------------------------------


def test_legacy_facade_routes_to_registry():
    """`ui.execution_algorithms.preview_execution_algorithm` must continue to work."""

    from tradingagents.ui.execution_algorithms import preview_execution_algorithm

    plan = preview_execution_algorithm(
        algorithm="bracket_order",
        symbol="NVDA",
        side="buy",
        notional=1000,
        reference_price=200,
    )
    assert isinstance(plan, ExecutionAlgorithmPlan)
    assert plan.algorithm == "bracket_order"
    assert plan.symbol == "NVDA"
