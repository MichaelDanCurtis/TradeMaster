"""Additive tables; existing UI tables and columns are untouched."""
from datetime import datetime
from typing import Any

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from tradingagents.ui.models import UTCDateTime, new_id, now_utc


class StrategyRecord(SQLModel, table=True):
    __tablename__ = "research_strategies"
    strategy_id: str = Field(default_factory=lambda: new_id("strategy"), primary_key=True)
    name: str
    hypothesis: str
    rationale: str
    revision: int = 1
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))
    updated_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class StrategyVersionRecord(SQLModel, table=True):
    __tablename__ = "research_strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "content_hash"),)
    version_id: str = Field(default_factory=lambda: new_id("sv"), primary_key=True)
    strategy_id: str = Field(foreign_key="research_strategies.strategy_id", index=True)
    parent_version_id: str | None = Field(default=None, foreign_key="research_strategy_versions.version_id")
    content_hash: str
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class ResearchFamilyRecord(SQLModel, table=True):
    __tablename__ = "research_families"
    family_id: str = Field(primary_key=True)
    strategy_id: str = Field(foreign_key="research_strategies.strategy_id")
    max_trials: int
    compute_budget_usd: str


class ResearchPlanRecord(SQLModel, table=True):
    __tablename__ = "research_plans"
    plan_id: str = Field(default_factory=lambda: new_id("rp"), primary_key=True)
    strategy_id: str = Field(foreign_key="research_strategies.strategy_id", index=True)
    family_id: str = Field(foreign_key="research_families.family_id", index=True)
    content_hash: str = Field(unique=True)
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class DatasetSnapshotRecord(SQLModel, table=True):
    __tablename__ = "research_snapshots"
    snapshot_id: str = Field(default_factory=lambda: new_id("ds"), primary_key=True)
    content_hash: str = Field(unique=True)
    evidence_kind: str = Field(index=True)
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class ExperimentRecord(SQLModel, table=True):
    __tablename__ = "research_experiments"
    experiment_id: str = Field(default_factory=lambda: new_id("exp"), primary_key=True)
    plan_id: str = Field(foreign_key="research_plans.plan_id", index=True)
    strategy_id: str = Field(foreign_key="research_strategies.strategy_id", index=True)
    family_id: str = Field(foreign_key="research_families.family_id", index=True)
    snapshot_id: str = Field(foreign_key="research_snapshots.snapshot_id")
    parent_experiment_id: str | None = Field(default=None, foreign_key="research_experiments.experiment_id")
    idempotency_key: str = Field(unique=True)
    request_hash: str
    evaluation: str
    engine: str
    state: str = Field(default="queued", index=True)
    trial_count: int
    attempts: int = 0
    lease_owner: str | None = None
    lease_until: datetime | None = Field(default=None, sa_column=Column(UTCDateTime))
    started_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime))
    ended_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime))
    failure_reason: str | None = None
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    cost_usd: str = "0"
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class ExperimentEventRecord(SQLModel, table=True):
    __tablename__ = "research_experiment_events"
    event_id: str = Field(default_factory=lambda: new_id("ree"), primary_key=True)
    experiment_id: str = Field(foreign_key="research_experiments.experiment_id", index=True)
    event_type: str
    message: str
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class HoldoutUseRecord(SQLModel, table=True):
    __tablename__ = "research_holdout_uses"
    use_id: str = Field(default_factory=lambda: new_id("hu"), primary_key=True)
    family_id: str = Field(foreign_key="research_families.family_id", index=True)
    experiment_id: str = Field(foreign_key="research_experiments.experiment_id")
    start_date: str
    end_date: str


class ResearchWorkerRecord(SQLModel, table=True):
    __tablename__ = "research_workers"
    worker_id: str = Field(primary_key=True)
    engine_build: str
    state: str
    experiment_id: str | None = None
    last_seen_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class ResearchModelCallRecord(SQLModel, table=True):
    __tablename__ = "research_model_calls"
    __table_args__ = (UniqueConstraint("experiment_id", "request_hash"),)
    call_id: str = Field(default_factory=lambda: new_id("rmc"), primary_key=True)
    experiment_id: str = Field(foreign_key="research_experiments.experiment_id", index=True)
    family_id: str = Field(foreign_key="research_families.family_id", index=True)
    version_id: str = Field(foreign_key="research_strategy_versions.version_id")
    notice_id: str
    input_hash: str
    input_as_of: datetime = Field(sa_column=Column(UTCDateTime, nullable=False))
    request_hash: str
    request: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    provider_fingerprint: str
    worker_id: str
    reserved_cost_usd: str
    charged_cost_usd: str
    state: str = "reserved"
    output_artifact: str | None = None
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))
    dispatched_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime))
    completed_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime))


class StrategyDesignRecord(SQLModel, table=True):
    __tablename__ = "research_strategy_designs"
    design_id: str = Field(default_factory=lambda: new_id("design"), primary_key=True)
    strategy_id: str = Field(foreign_key="research_strategies.strategy_id", index=True)
    family_id: str = Field(foreign_key="research_families.family_id", index=True)
    idempotency_key: str = Field(unique=True)
    request_hash: str
    request: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    reserved_cost_usd: str
    charged_cost_usd: str
    state: str = "reserved"
    receipt: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))
    deadline_at: datetime = Field(sa_column=Column(UTCDateTime, nullable=False))
    dispatched_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime))
    completed_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime))
