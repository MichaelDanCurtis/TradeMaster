import pytest

from tradingagents.ui.room_policy import (
    ROOM_DECISION_ACTIONS,
    enforce_room_tool,
    evaluate_room_tool,
    get_room_policy,
)


def test_room_policy_allows_research_tools_without_broker_tools():
    research = get_room_policy("research")

    assert "research-runner" in research.tool_grants
    assert "llm-provider" in research.tool_grants
    assert "broker-paper-preview" not in research.tool_grants
    assert evaluate_room_tool("research", "research-runner").allowed is True
    assert evaluate_room_tool("research", "broker-paper-preview").allowed is False


def test_enforce_room_tool_rejects_broker_access_from_research_room():
    with pytest.raises(PermissionError, match="Research Office does not grant broker-paper-preview"):
        enforce_room_tool("research", "broker-paper-preview")


def test_brokerage_floor_can_preview_but_not_live_submit():
    assert enforce_room_tool("market", "broker-paper-preview").allowed is True
    assert enforce_room_tool("market", "execution-algorithm-preview").allowed is True

    denied = evaluate_room_tool("market", "broker-trade-submit")

    assert denied.allowed is False
    assert "broker-trade-submit" in denied.reason


def test_all_rooms_share_operator_decision_actions():
    assert ROOM_DECISION_ACTIONS == ("accept", "reject", "revise", "defer", "escalate")
    assert get_room_policy("transactions").decision_actions == ROOM_DECISION_ACTIONS
