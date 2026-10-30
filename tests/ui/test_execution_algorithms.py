import pytest

from tradingagents.ui.execution_algorithms import preview_execution_algorithm


def test_trailing_stop_algorithm_builds_entry_and_stop_legs():
    plan = preview_execution_algorithm(
        algorithm="trailing_stop",
        symbol="nvda",
        side="buy",
        notional=1000,
        reference_price=200,
    )

    assert plan.algorithm == "trailing_stop"
    assert plan.symbol == "NVDA"
    assert plan.estimated_quantity == 5
    assert [leg.kind for leg in plan.legs] == ["market_entry", "trailing_stop"]
    assert plan.legs[1].parameters["trail_percent"] == 5


def test_bracket_algorithm_builds_profit_and_loss_guards():
    plan = preview_execution_algorithm(
        algorithm="bracket_order",
        symbol="NVDA",
        side="buy",
        notional=1000,
        reference_price=200,
    )

    assert [leg.kind for leg in plan.legs] == ["market_entry", "take_profit", "stop_loss"]
    assert plan.legs[1].price == 216
    assert plan.legs[2].price == 190


def test_dca_ladder_algorithm_splits_notional_across_ladder_prices():
    plan = preview_execution_algorithm(
        algorithm="dca_ladder",
        symbol="NVDA",
        side="buy",
        notional=1000,
        reference_price=200,
    )

    assert len(plan.legs) == 4
    assert [leg.kind for leg in plan.legs] == ["ladder_entry", "ladder_entry", "ladder_entry", "ladder_entry"]
    assert [leg.price for leg in plan.legs] == [200, 194, 188, 180]
    assert sum(leg.notional for leg in plan.legs) == 1000


def test_execution_algorithms_reject_invalid_inputs():
    with pytest.raises(ValueError, match="unsupported execution algorithm"):
        preview_execution_algorithm(
            algorithm="moonshot",
            symbol="NVDA",
            side="buy",
            notional=1000,
            reference_price=200,
        )
