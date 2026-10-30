"""Smoke tests for every registered execution algorithm.

For each algorithm in the registry, exercises both sides (buy, sell) at a
common reference and asserts the universal invariants:

- Returns an ``ExecutionAlgorithmPlan``
- Plan algorithm name matches what was requested
- Plan symbol is normalized
- Determinism: same context → same plan (re-running yields identical legs)

Algorithms that intentionally produce an empty plan under gating
conditions (kelly_fraction with poor edge defaults; sector_rotation
outside eligibility) are exempt from the "must produce at least one leg"
check; the test relies on the algorithm's own validation to flag misuse.
"""

from __future__ import annotations

import pytest

from tradingagents.algorithms import (
    AlgorithmContext,
    ExecutionAlgorithmPlan,
    get,
    list_algorithms,
    preview,
)


REFERENCE_PRICE = 200.0
NOTIONAL = 1000.0
SYMBOL = "NVDA"


@pytest.mark.parametrize("cls", list_algorithms(), ids=lambda c: c.name)
@pytest.mark.parametrize("side", ["buy", "sell"])
def test_algorithm_produces_valid_plan(cls, side):
    plan = preview(
        algorithm=cls.name,
        symbol=SYMBOL,
        side=side,
        notional=NOTIONAL,
        reference_price=REFERENCE_PRICE,
    )
    assert isinstance(plan, ExecutionAlgorithmPlan)
    assert plan.algorithm == cls.name
    assert plan.symbol == SYMBOL
    assert plan.side == side
    assert plan.reference_price == REFERENCE_PRICE
    for leg in plan.legs:
        assert leg.symbol  # non-empty
        assert leg.side in {"buy", "sell"}
        assert leg.notional >= 0
        assert leg.estimated_quantity >= 0


@pytest.mark.parametrize("cls", list_algorithms(), ids=lambda c: c.name)
def test_algorithm_is_deterministic(cls):
    """Same input twice → identical plan."""

    a = preview(
        algorithm=cls.name,
        symbol=SYMBOL,
        side="buy",
        notional=NOTIONAL,
        reference_price=REFERENCE_PRICE,
    )
    b = preview(
        algorithm=cls.name,
        symbol=SYMBOL,
        side="buy",
        notional=NOTIONAL,
        reference_price=REFERENCE_PRICE,
    )
    assert a.model_dump() == b.model_dump()


@pytest.mark.parametrize("cls", list_algorithms(), ids=lambda c: c.name)
def test_algorithm_class_is_instantiable(cls):
    instance = cls()
    ctx = AlgorithmContext(
        symbol=SYMBOL,
        side="buy",
        notional=NOTIONAL,
        reference_price=REFERENCE_PRICE,
        parameters={},
    )
    plan = instance.propose(ctx)
    assert isinstance(plan, ExecutionAlgorithmPlan)


def test_get_returns_fresh_instances():
    a = get("trailing_stop")
    b = get("trailing_stop")
    assert a is not b
    assert type(a) is type(b)


# ---------------------------------------------------------------------------
# Category-specific invariants
# ---------------------------------------------------------------------------


def test_time_based_algorithms_legs_sum_to_notional():
    """TWAP/VWAP/POV/Iceberg/IS distribute the parent notional across slices."""

    for name in ("twap", "vwap", "pov", "iceberg", "implementation_shortfall"):
        plan = preview(
            algorithm=name,
            symbol=SYMBOL,
            side="buy",
            notional=NOTIONAL,
            reference_price=REFERENCE_PRICE,
        )
        total = sum(leg.notional for leg in plan.legs)
        # Allow 1 cent rounding tolerance — algorithms absorb remainder into last leg.
        assert abs(total - NOTIONAL) < 0.01, f"{name}: sum(notional)={total} != {NOTIONAL}"


def test_bracket_order_has_three_legs_and_oco_exits():
    plan = preview(
        algorithm="bracket_order",
        symbol=SYMBOL,
        side="buy",
        notional=NOTIONAL,
        reference_price=REFERENCE_PRICE,
    )
    kinds = [leg.kind for leg in plan.legs]
    assert kinds == ["market_entry", "take_profit", "stop_loss"]
    # exits are opposite-side
    assert plan.legs[1].side == "sell"
    assert plan.legs[2].side == "sell"
    # take_profit above reference, stop_loss below (for a buy)
    assert plan.legs[1].price > plan.legs[0].price
    assert plan.legs[2].price < plan.legs[0].price


def test_dca_ladder_preserves_legacy_default_schedule():
    """Pin the exact legacy ladder behavior the old tests already cover."""

    plan = preview(
        algorithm="dca_ladder",
        symbol=SYMBOL,
        side="buy",
        notional=NOTIONAL,
        reference_price=REFERENCE_PRICE,
    )
    assert [leg.price for leg in plan.legs] == [200, 194, 188, 180]
    assert sum(leg.notional for leg in plan.legs) == NOTIONAL


def test_pair_spread_emits_active_and_hedge_legs():
    plan = preview(
        algorithm="pair_spread",
        symbol="NVDA",
        side="buy",
        notional=NOTIONAL,
        reference_price=REFERENCE_PRICE,
        parameters={"hedge_symbol": "smh", "hedge_ratio": 0.8, "hedge_price": 250},
    )
    kinds = [leg.kind for leg in plan.legs]
    assert kinds == ["active_leg", "hedge_leg"]
    assert plan.legs[1].symbol == "SMH"
    assert plan.legs[1].side == "sell"


def test_kelly_returns_no_legs_for_non_positive_edge():
    plan = preview(
        algorithm="kelly_fraction",
        symbol=SYMBOL,
        side="buy",
        notional=NOTIONAL,
        reference_price=REFERENCE_PRICE,
        parameters={"win_probability": 0.4, "win_loss_ratio": 1.0},
    )
    assert plan.legs == []
    assert plan.notional == 0.0


def test_sector_rotation_gates_out_of_band():
    plan = preview(
        algorithm="sector_rotation",
        symbol=SYMBOL,
        side="buy",
        notional=NOTIONAL,
        reference_price=REFERENCE_PRICE,
        parameters={"sector_rank": 9, "max_eligible_rank": 3},
    )
    assert plan.legs == []


def test_earnings_drift_gates_on_negative_surprise():
    plan = preview(
        algorithm="earnings_drift",
        symbol=SYMBOL,
        side="buy",
        notional=NOTIONAL,
        reference_price=REFERENCE_PRICE,
        parameters={"surprise_percent": -2.0, "guidance_raised": True},
    )
    assert plan.legs == []
