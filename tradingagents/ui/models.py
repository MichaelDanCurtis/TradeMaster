from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, JSON
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class RunRecord(SQLModel, table=True):
    __tablename__ = "ui_runs"

    run_id: str = Field(default_factory=lambda: new_id("run"), primary_key=True)
    ticker: str = Field(index=True)
    trade_date: str = Field(index=True)
    status: str = Field(default="queued", index=True)
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    final_rating: str | None = None
    final_action: str | None = None
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class RunEventRecord(SQLModel, table=True):
    __tablename__ = "ui_run_events"

    event_id: str = Field(default_factory=lambda: new_id("evt"), primary_key=True)
    run_id: str = Field(index=True)
    sequence: int = Field(index=True)
    type: str = Field(index=True)
    node: str | None = None
    message: str
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class ReportScheduleRecord(SQLModel, table=True):
    __tablename__ = "report_schedules"

    schedule_id: str = Field(default_factory=lambda: new_id("sched"), primary_key=True)
    name: str
    symbol: str = Field(index=True)
    cadence: str = Field(index=True)
    broker_mode: str = Field(default="disabled", index=True)
    execution_mode: str = Field(default="real", index=True)
    enabled: bool = Field(default=True, index=True)
    last_run_id: str | None = Field(default=None, index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    last_ran_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime, index=True))
    next_run_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime, index=True))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class ObservabilityTraceRecord(SQLModel, table=True):
    __tablename__ = "observability_traces"

    trace_id: str = Field(default_factory=lambda: new_id("trace"), primary_key=True)
    run_id: str = Field(index=True, unique=True)
    provider: str = Field(default="local", index=True)
    status: str = Field(default="running", index=True)
    external_trace_id: str | None = Field(default=None, index=True)
    metadata_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    cost: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class DecisionRecord(SQLModel, table=True):
    __tablename__ = "ui_decisions"

    decision_id: str = Field(default_factory=lambda: new_id("dec"), primary_key=True)
    run_id: str = Field(index=True)
    rating: str
    action: str
    thesis: str
    risk_notes: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class TradeIntentRecord(SQLModel, table=True):
    __tablename__ = "ui_trade_intents"

    intent_id: str = Field(default_factory=lambda: new_id("ti"), primary_key=True)
    run_id: str = Field(index=True)
    symbol: str
    side: str
    notional: float
    order_type: str = "market"
    status: str = Field(default="previewed", index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class ApprovalRecord(SQLModel, table=True):
    __tablename__ = "ui_approvals"

    approval_id: str = Field(default_factory=lambda: new_id("appr"), primary_key=True)
    intent_id: str = Field(index=True)
    actor: str = Field(index=True)
    action: str = Field(index=True)
    before_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    after_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class ApprovalLedgerRecord(SQLModel, table=True):
    __tablename__ = "approval_ledger"

    approval_id: str = Field(default_factory=lambda: new_id("ledger"), primary_key=True)
    room_id: str = Field(index=True)
    source: str = Field(index=True)
    entity_type: str = Field(index=True)
    entity_id: str = Field(index=True)
    action: str = Field(index=True)
    actor: str = Field(index=True)
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class AgentTriggerRecord(SQLModel, table=True):
    __tablename__ = "agent_triggers"

    trigger_id: str = Field(default_factory=lambda: new_id("trigger"), primary_key=True)
    name: str
    room_id: str = Field(index=True)
    trigger_type: str = Field(index=True)
    target_agent: str = Field(index=True)
    symbol: str | None = Field(default=None, index=True)
    condition: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    workflow_id: str | None = Field(default=None, index=True)
    enabled: bool = Field(default=True, index=True)
    last_fired_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime, index=True))
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class AgentOperationRecord(SQLModel, table=True):
    __tablename__ = "agent_operations"

    operation_id: str = Field(default_factory=lambda: new_id("agentop"), primary_key=True)
    agent_id: str = Field(index=True)
    agent_name: str
    room_id: str = Field(index=True)
    symbol: str = Field(index=True)
    operation_type: str = Field(index=True)
    status: str = Field(default="queued", index=True)
    authority: str = Field(index=True)
    source_workflow_id: str | None = Field(default=None, index=True)
    linked_run_id: str | None = Field(default=None, index=True)
    linked_execution_program_id: str | None = Field(default=None, index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    started_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime, index=True))
    completed_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime, index=True))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class TradeThesisRecord(SQLModel, table=True):
    __tablename__ = "trade_theses"

    thesis_id: str = Field(default_factory=lambda: new_id("thesis"), primary_key=True)
    symbol: str = Field(index=True)
    source_report_id: str | None = Field(default=None, index=True)
    source_room: str = Field(default="research", index=True)
    target_room: str = Field(default="market", index=True)
    direction: str = Field(index=True)
    horizon: str = Field(index=True)
    conviction: float = Field(default=0.0, index=True)
    status: str = Field(default="proposed", index=True)
    thesis: str
    catalysts: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    invalidation: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    risk_notes: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class PortfolioReviewRecord(SQLModel, table=True):
    __tablename__ = "portfolio_reviews"

    review_id: str = Field(default_factory=lambda: new_id("preview"), primary_key=True)
    symbol: str = Field(index=True)
    room_id: str = Field(default="portfolio", index=True)
    status: str = Field(default="draft", index=True)
    goals: str | None = None
    horizon: str | None = None
    risk_posture: str | None = None
    sector_focus: str | None = None
    constraints: str | None = None
    liquidity_needs: str | None = None
    thesis: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    missing_provider_facts: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class FundingAllocationReviewRecord(SQLModel, table=True):
    __tablename__ = "funding_allocation_reviews"

    review_id: str = Field(default_factory=lambda: new_id("funding"), primary_key=True)
    symbol: str = Field(index=True)
    source_thesis_id: str | None = Field(default=None, index=True)
    execution_program_id: str | None = Field(default=None, index=True)
    status: str = Field(default="draft", index=True)
    notional: float | None = None
    tracks: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    missing_provider_facts: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    approval_next_steps: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class ExecutionProgramRecord(SQLModel, table=True):
    __tablename__ = "execution_programs"

    program_id: str = Field(default_factory=lambda: new_id("program"), primary_key=True)
    symbol: str = Field(index=True)
    source_thesis_id: str | None = Field(default=None, index=True)
    algorithm: str = Field(index=True)
    state: str = Field(default="preview_ready", index=True)
    mode: str = Field(default="paper", index=True)
    approval_status: str = Field(default="required", index=True)
    live_submission_enabled: bool = Field(default=False, index=True)
    trigger_points: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    circuit_breakers: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    missing_provider_facts: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class ExecutionProgramEventRecord(SQLModel, table=True):
    __tablename__ = "execution_program_events"

    event_id: str = Field(default_factory=lambda: new_id("progevt"), primary_key=True)
    program_id: str = Field(index=True)
    event_type: str = Field(index=True)
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class BrokerOrderRecord(SQLModel, table=True):
    __tablename__ = "ui_broker_orders"

    order_id: str = Field(default_factory=lambda: new_id("bo"), primary_key=True)
    intent_id: str = Field(index=True)
    broker: str
    environment: str = Field(index=True)
    status: str = Field(index=True)
    broker_order_id: str | None = Field(default=None, index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class ProviderConfigRecord(SQLModel, table=True):
    __tablename__ = "ui_provider_configs"

    provider_id: str = Field(primary_key=True)
    name: str
    role: str = Field(index=True)
    status: str = Field(index=True)
    capabilities: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    primary_use: str
    control_surface: str = Field(index=True)
    write_authority: str = Field(index=True)
    enabled: bool = Field(default=False, index=True)
    secret_ref: str | None = Field(default=None, index=True)
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    health: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class ProviderRoleAssignmentRecord(SQLModel, table=True):
    __tablename__ = "provider_role_assignments"

    role_key: str = Field(primary_key=True)
    provider_id: str = Field(index=True)
    surface: str = Field(index=True)
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class MarketDataSnapshotRecord(SQLModel, table=True):
    __tablename__ = "market_data_snapshots"

    snapshot_id: str = Field(default_factory=lambda: new_id("mds"), primary_key=True)
    provider_id: str = Field(index=True)
    symbol: str = Field(index=True)
    snapshot_kind: str = Field(index=True)
    feed: str | None = Field(default=None, index=True)
    timeframe: str | None = Field(default=None, index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class PrivateOfficeEventRecord(SQLModel, table=True):
    __tablename__ = "private_office_events"

    event_id: str = Field(default_factory=lambda: new_id("poevt"), primary_key=True)
    event_type: str = Field(index=True)
    summary: str
    actor: str = Field(index=True)
    entity_id: str | None = Field(default=None, index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class AppSettingRecord(SQLModel, table=True):
    __tablename__ = "app_settings"

    setting_key: str = Field(primary_key=True)
    value: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class PrivateOfficeEntityRecord(SQLModel, table=True):
    __tablename__ = "private_office_entities"

    entity_id: str = Field(primary_key=True)
    entity_type: str = Field(index=True)
    label: str
    external_id: str | None = Field(default=None, index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class PrivateOfficeEdgeRecord(SQLModel, table=True):
    __tablename__ = "private_office_edges"

    edge_id: str = Field(default_factory=lambda: new_id("poedge"), primary_key=True)
    source_entity_id: str = Field(index=True)
    target_entity_id: str = Field(index=True)
    relationship: str = Field(index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class PortfolioMandateRecord(SQLModel, table=True):
    __tablename__ = "portfolio_mandates"

    mandate_id: str = Field(default_factory=lambda: new_id("mandate"), primary_key=True)
    name: str
    control_mode: str = Field(index=True)
    account_ref: str = Field(index=True)
    status: str = Field(default="draft", index=True)
    funding_limit: float
    max_position_percent: float
    max_drawdown_percent: float
    daily_turnover_limit_percent: float
    paper_mode_required: bool = Field(default=True, index=True)
    kill_switch_enabled: bool = Field(default=True, index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class AgentWorkflowRecord(SQLModel, table=True):
    __tablename__ = "agent_workflows"

    workflow_id: str = Field(default_factory=lambda: new_id("workflow"), primary_key=True)
    name: str
    agent_class: str = Field(index=True)
    graph_runtime: str = Field(index=True)
    status: str = Field(default="draft", index=True)
    nodes: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    edges: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    required_provider_roles: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class AgentPackRecord(SQLModel, table=True):
    __tablename__ = "agent_packs"

    pack_id: str = Field(primary_key=True)
    source_url: str | None = Field(default=None)
    source_commit: str | None = Field(default=None, index=True)
    license: str | None = Field(default=None)
    status: str = Field(default="imported", index=True)
    manifest: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    imported_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class ImportedAgentRecord(SQLModel, table=True):
    __tablename__ = "imported_agents"

    agent_id: str = Field(primary_key=True)
    pack_id: str = Field(index=True)
    source_slug: str = Field(index=True)
    name: str
    description: str
    agent_class: str = Field(index=True)
    system_prompt: str
    guardrails: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    skills: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    commands: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    required_provider_roles: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    required_connectors: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    tool_policy: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    output_schema: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    security_profile: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="imported", index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class ImportedSkillRecord(SQLModel, table=True):
    __tablename__ = "imported_skills"

    skill_id: str = Field(primary_key=True)
    pack_id: str = Field(index=True)
    source_path: str
    name: str
    description: str
    instructions_markdown: str
    references: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    scripts: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    artifact_requirements: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="imported", index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class McpConnectorRecord(SQLModel, table=True):
    __tablename__ = "mcp_connectors"

    connector_id: str = Field(primary_key=True)
    name: str
    url: str
    provider_id: str | None = Field(default=None, index=True)
    required_secret_ref: str | None = Field(default=None, index=True)
    capabilities: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    health: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    enabled: bool = Field(default=False, index=True)
    subscription_required: bool = Field(default=True, index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class SnapshotManifestRecord(SQLModel, table=True):
    __tablename__ = "snapshot_manifests"

    snapshot_id: str = Field(primary_key=True)
    storage_profile: str = Field(index=True)
    encryption_mode: str = Field(index=True)
    offsite_target: str | None = Field(default=None, index=True)
    manifest: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class WatcherRecord(SQLModel, table=True):
    __tablename__ = "ui_watchers"

    watcher_id: str = Field(default_factory=lambda: new_id("w"), primary_key=True)
    name: str
    symbol: str = Field(index=True)
    condition_type: str = Field(index=True)
    threshold: float
    enabled: bool = Field(default=True, index=True)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    linked_position_id: str | None = Field(default=None, index=True)
    linked_run_id: str | None = Field(default=None, index=True)
    last_fired_at: datetime | None = Field(
        default=None, sa_column=Column(UTCDateTime, index=True)
    )
    fire_count: int = Field(default=0)
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    updated_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class QuickScanRecord(SQLModel, table=True):
    """One cheap wide-pass LLM read of a symbol (Quick Scan funnel stage).

    Deliberately flat: the scan is a screening verdict, not a committee
    decision — stance/conviction/thesis/catalyst/risk are the whole payload.
    """

    __tablename__ = "ui_quick_scans"

    scan_row_id: str = Field(default_factory=lambda: new_id("qs"), primary_key=True)
    symbol: str = Field(index=True)
    stance: str = Field(index=True)
    conviction: int = Field(default=0)
    thesis: str
    catalyst: str
    risk: str
    model: str
    created_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )


class WatcherFireRecord(SQLModel, table=True):
    __tablename__ = "ui_watcher_fires"

    fire_id: str = Field(default_factory=lambda: new_id("wf"), primary_key=True)
    watcher_id: str = Field(index=True)
    symbol: str = Field(index=True)
    fired_at: datetime = Field(
        default_factory=now_utc, sa_column=Column(UTCDateTime, index=True)
    )
    observed_value: float
    threshold: float
    condition_type: str
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
