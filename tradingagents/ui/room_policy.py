from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RoomId = Literal["dashboard", "research", "market", "transactions", "settings"]
DecisionAction = Literal["accept", "reject", "revise", "defer", "escalate"]
ToolGrant = str

ROOM_DECISION_ACTIONS: tuple[DecisionAction, ...] = (
    "accept",
    "reject",
    "revise",
    "defer",
    "escalate",
)


@dataclass(frozen=True)
class RoomPolicy:
    room_id: RoomId
    label: str
    mission: str
    tool_grants: tuple[ToolGrant, ...]
    policies: tuple[str, ...]
    decision_actions: tuple[DecisionAction, ...] = ROOM_DECISION_ACTIONS


@dataclass(frozen=True)
class RoomToolDecision:
    room_id: str
    tool_grant: str
    allowed: bool
    reason: str


ROOM_POLICIES: tuple[RoomPolicy, ...] = (
    RoomPolicy(
        room_id="dashboard",
        label="Briefing Room",
        mission="Morning and meeting surface for agent reports, position posture, liabilities, and recommendations.",
        tool_grants=(
            "research-overview-read",
            "market-data-read",
            "portfolio-read",
            "account-read",
            "agent-message-read",
            "research-runner",
        ),
        policies=(
            "Briefing agents can summarize and recommend, but cannot submit broker orders.",
            "Every recommendation must end in accept, reject, revise, defer, or escalate.",
            "Liability, cash, and exception items must be visible before trade program approvals.",
        ),
    ),
    RoomPolicy(
        room_id="research",
        label="Research Office",
        mission="Investment committee and research desk for deep work, theses, allocation analysis, and agent-chain design.",
        tool_grants=(
            "research-overview-read",
            "market-data-read",
            "research-runner",
            "llm-provider",
            "agent-message-read",
            "trace-export",
            "strategy-read",
            "strategy-draft",
            "strategy-experiment",
            "deployment-read",
            "deployment-request",
        ),
        policies=(
            "Research agents cannot submit, stage, or modify broker orders.",
            "Research output is advisory until a broker or compliance agent converts it into an execution proposal.",
            "Source evidence, assumptions, and uncertainty must remain visible with each thesis.",
        ),
    ),
    RoomPolicy(
        room_id="market",
        label="Brokerage Floor",
        mission="Live execution monitoring, expected-vs-actual charts, paper algorithms, and active trade-program oversight.",
        tool_grants=(
            "market-data-read",
            "portfolio-read",
            "broker-paper-preview",
            "execution-algorithm-preview",
            "deployment-read",
            "deployment-request",
            "deployment-manage",
        ),
        policies=(
            "Paper previews and algorithm plans require explicit approval before any broker submission path is enabled.",
            "Execution agents must obey symbolic circuit breakers before proposing a trade program.",
            "Live broker trade submission remains unavailable unless a future approval-gated tool grant is added.",
        ),
    ),
    RoomPolicy(
        room_id="transactions",
        label="Operations & Private Office",
        mission="Money movement, holdings, goals, property dossiers, document vault, reconciliation, and compliance routing.",
        tool_grants=(
            "account-read",
            "portfolio-read",
            "agent-message-read",
            "document-vault-read",
            "paper-account-review",
            "paper-account-reconcile",
            "compliance-gateway",
            "backup-status-read",
        ),
        policies=(
            "All agent-to-agent requests entering the private office pass through the compliance gateway.",
            "Money movement, document changes, and liability decisions require approval and audit trail.",
            "Private-office agents can request broker review, but cannot directly trade.",
        ),
    ),
    RoomPolicy(
        room_id="settings",
        label="Settings",
        mission="Provider wiring, account routing, developer-mode LLMs, backup posture, traces, and administrative controls.",
        tool_grants=(
            "research-overview-read",
            "provider-configure",
            "schedule-manage",
            "trace-export",
            "backup-status-read",
        ),
        policies=(
            "Secrets stay out of reports and UI payloads.",
            "Developer-mode LLM sources must be visibly marked before use.",
            "Provider changes must not silently grant trade authority to research rooms.",
        ),
    ),
)


def list_room_policies() -> tuple[RoomPolicy, ...]:
    return ROOM_POLICIES


def get_room_policy(room_id: str) -> RoomPolicy:
    for policy in ROOM_POLICIES:
        if policy.room_id == room_id:
            return policy
    raise KeyError(room_id)


def evaluate_room_tool(room_id: str, tool_grant: str) -> RoomToolDecision:
    try:
        policy = get_room_policy(room_id)
    except KeyError:
        return RoomToolDecision(
            room_id=room_id,
            tool_grant=tool_grant,
            allowed=False,
            reason=f"Unknown room {room_id}",
        )

    if tool_grant in policy.tool_grants:
        return RoomToolDecision(
            room_id=room_id,
            tool_grant=tool_grant,
            allowed=True,
            reason=f"{policy.label} grants {tool_grant}",
        )

    return RoomToolDecision(
        room_id=room_id,
        tool_grant=tool_grant,
        allowed=False,
        reason=f"{policy.label} does not grant {tool_grant}",
    )


def enforce_room_tool(room_id: str, tool_grant: str) -> RoomToolDecision:
    decision = evaluate_room_tool(room_id, tool_grant)
    if not decision.allowed:
        raise PermissionError(decision.reason)
    return decision
