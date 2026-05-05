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
