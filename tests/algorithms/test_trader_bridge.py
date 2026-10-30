"""Tests for the Trader → algorithm-plan bridge."""

from __future__ import annotations

import pytest

from tradingagents.agents.schemas import TraderAction, TraderProposal
from tradingagents.algorithms.trader_bridge import build_order_plan_from_proposal


def _proposal(action: TraderAction, *, entry_price: float | None = None) -> TraderProposal:
    return TraderProposal(
        action=action,
        reasoning="test",
        entry_price=entry_price,
    )


def test_hold_proposal_returns_none():
    plan = build_order_plan_from_proposal(
        _proposal(TraderAction.HOLD),
        algorithm="twap",
        symbol="NVDA",
        notional=1000,
        reference_price=200,
    )
    assert plan is None


def test_buy_proposal_routes_to_buy_side():
    plan = build_order_plan_from_proposal(
        _proposal(TraderAction.BUY),
        algorithm="bracket_order",
        symbol="NVDA",
        notional=1000,
        reference_price=200,
    )
    assert plan is not None
    assert plan.side == "buy"
    assert plan.algorithm == "bracket_order"


def test_sell_proposal_routes_to_sell_side():
    plan = build_order_plan_from_proposal(
        _proposal(TraderAction.SELL),
        algorithm="trailing_stop",
        symbol="NVDA",
        notional=1000,
        reference_price=200,
    )
    assert plan is not None
    assert plan.side == "sell"


def test_proposal_entry_price_used_when_reference_omitted():
    plan = build_order_plan_from_proposal(
        _proposal(TraderAction.BUY, entry_price=215.5),
        algorithm="twap",
        symbol="NVDA",
        notional=1000,
        reference_price=None,
    )
    assert plan is not None
    assert plan.reference_price == 215.5


def test_missing_reference_and_entry_raises():
    with pytest.raises(ValueError, match="reference_price required"):
        build_order_plan_from_proposal(
            _proposal(TraderAction.BUY, entry_price=None),
            algorithm="twap",
            symbol="NVDA",
            notional=1000,
            reference_price=None,
        )


def test_unknown_algorithm_propagates_registry_error():
    with pytest.raises(ValueError, match="unsupported execution algorithm"):
        build_order_plan_from_proposal(
            _proposal(TraderAction.BUY),
            algorithm="moonshot",
            symbol="NVDA",
            notional=1000,
            reference_price=200,
        )


def test_parameters_pass_through_to_algorithm():
    plan = build_order_plan_from_proposal(
        _proposal(TraderAction.BUY),
        algorithm="twap",
        symbol="NVDA",
        notional=1000,
        reference_price=200,
        parameters={"slices": 3, "window_minutes": 15},
    )
    assert plan is not None
    assert len(plan.legs) == 3
