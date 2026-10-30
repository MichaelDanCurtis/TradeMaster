"""Additive lifecycle, immutable funding terms and promotion reviews."""
from datetime import datetime
from typing import Any

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from tradingagents.ui.models import UTCDateTime, new_id, now_utc


class StrategyDeploymentRecord(SQLModel, table=True):
    __tablename__ = "research_deployments"
    deployment_id: str = Field(default_factory=lambda:new_id("dep"),primary_key=True)
    name: str
    version_id: str = Field(foreign_key="research_strategy_versions.version_id",index=True)
    experiment_id: str = Field(foreign_key="research_experiments.experiment_id")
    account_key: str = Field(index=True)
    account: dict[str,Any] = Field(sa_column=Column(JSON,nullable=False))
    idempotency_key: str = Field(unique=True)
    request_hash: str
    state: str = Field(default="draft",index=True)
    revision: int = 1
    pending_terms_id: str
    active_terms_id: str | None = None
    active_review_id: str | None = None
    created_at: datetime = Field(default_factory=now_utc,sa_column=Column(UTCDateTime,nullable=False))
    updated_at: datetime = Field(default_factory=now_utc,sa_column=Column(UTCDateTime,nullable=False))


class DeploymentTermsRecord(SQLModel, table=True):
    __tablename__ = "research_deployment_terms"
    terms_id: str = Field(default_factory=lambda:new_id("dterms"),primary_key=True)
    deployment_id: str = Field(foreign_key="research_deployments.deployment_id",index=True)
    content_hash: str
    payload: dict[str,Any] = Field(sa_column=Column(JSON,nullable=False))
    created_at: datetime = Field(default_factory=now_utc,sa_column=Column(UTCDateTime,nullable=False))


class DeploymentCapitalFlow(SQLModel, table=True):
    __tablename__ = "research_deployment_capital_flows"
    flow_id: str = Field(default_factory=lambda:new_id("dcf"),primary_key=True)
    deployment_id: str = Field(foreign_key="research_deployments.deployment_id",index=True)
    account_key: str = Field(index=True)
    revision: int
    action: str
    amount_usd: str
    terms_id: str = Field(foreign_key="research_deployment_terms.terms_id")
    reconciliation_id: str = Field(foreign_key="paper_account_reconciliations.reconciliation_id")
    review_id: str | None = Field(default=None,foreign_key="research_promotion_reviews.review_id")
    actor: str
    content_hash: str
    payload: dict[str,Any] = Field(sa_column=Column(JSON,nullable=False))
    effective_at: datetime = Field(default_factory=now_utc,sa_column=Column(UTCDateTime,nullable=False))


class PromotionReviewRecord(SQLModel, table=True):
    __tablename__ = "research_promotion_reviews"
    review_id: str = Field(default_factory=lambda:new_id("prv"),primary_key=True)
    deployment_id: str = Field(foreign_key="research_deployments.deployment_id",index=True)
    deployment_revision: int
    terms_id: str = Field(foreign_key="research_deployment_terms.terms_id")
    reconciliation_id: str = Field(foreign_key="paper_account_reconciliations.reconciliation_id")
    content_hash: str
    payload: dict[str,Any] = Field(sa_column=Column(JSON,nullable=False))
    expires_at: datetime = Field(sa_column=Column(UTCDateTime,nullable=False))
    created_at: datetime = Field(default_factory=now_utc,sa_column=Column(UTCDateTime,nullable=False))


class DeploymentEventRecord(SQLModel, table=True):
    __tablename__ = "research_deployment_events"
    event_id: str = Field(default_factory=lambda:new_id("devt"),primary_key=True)
    deployment_id: str = Field(foreign_key="research_deployments.deployment_id",index=True)
    revision: int
    action: str
    actor: str
    reason: str
    payload: dict[str,Any] = Field(default_factory=dict,sa_column=Column(JSON,nullable=False))
    created_at: datetime = Field(default_factory=now_utc,sa_column=Column(UTCDateTime,nullable=False))


class DeploymentProgramLink(SQLModel, table=True):
    __tablename__ = "research_deployment_programs"
    __table_args__ = (UniqueConstraint("deployment_id","program_id"),)
    link_id: str = Field(default_factory=lambda:new_id("dprog"),primary_key=True)
    deployment_id: str = Field(foreign_key="research_deployments.deployment_id",index=True)
    program_id: str = Field(foreign_key="execution_programs.program_id",unique=True)
    created_at: datetime = Field(default_factory=now_utc,sa_column=Column(UTCDateTime,nullable=False))


class DeploymentEvaluationRecord(SQLModel, table=True):
    __tablename__ = "research_deployment_evaluations"
    evaluation_id: str = Field(default_factory=lambda:new_id("deval"),primary_key=True)
    deployment_id: str = Field(foreign_key="research_deployments.deployment_id",index=True)
    terms_id: str = Field(foreign_key="research_deployment_terms.terms_id")
    request_hash: str = Field(unique=True)
    payload: dict[str,Any] = Field(sa_column=Column(JSON,nullable=False))
    created_at: datetime = Field(default_factory=now_utc,sa_column=Column(UTCDateTime,nullable=False))


class DeploymentOrderTargetRecord(SQLModel, table=True):
    __tablename__ = "research_deployment_order_targets"
    target_id: str = Field(default_factory=lambda:new_id("dtgt"),primary_key=True)
    evaluation_id: str = Field(foreign_key="research_deployment_evaluations.evaluation_id",index=True)
    deployment_id: str = Field(foreign_key="research_deployments.deployment_id",index=True)
    terms_id: str = Field(foreign_key="research_deployment_terms.terms_id")
    content_hash: str
    order: dict[str,Any] = Field(sa_column=Column(JSON,nullable=False))
    created_at: datetime = Field(default_factory=now_utc,sa_column=Column(UTCDateTime,nullable=False))


class DeploymentEvaluationJob(SQLModel, table=True):
    __tablename__ = "research_deployment_jobs"
    job_id: str = Field(default_factory=lambda:new_id("djob"),primary_key=True)
    deployment_id: str = Field(foreign_key="research_deployments.deployment_id",index=True)
    terms_id: str = Field(foreign_key="research_deployment_terms.terms_id")
    account_key: str = Field(index=True)
    request_hash: str = Field(unique=True)
    request: dict[str,Any] = Field(sa_column=Column(JSON,nullable=False))
    state: str = Field(default="queued",index=True)
    owner: str | None = None
    lease_until: datetime | None = Field(default=None,sa_column=Column(UTCDateTime))
    deadline: datetime | None = Field(default=None,sa_column=Column(UTCDateTime))
    result: dict[str,Any] | None = Field(default=None,sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=now_utc,sa_column=Column(UTCDateTime,nullable=False))
    started_at: datetime | None = Field(default=None,sa_column=Column(UTCDateTime))
    finished_at: datetime | None = Field(default=None,sa_column=Column(UTCDateTime))


class DeploymentWorkerRecord(SQLModel, table=True):
    __tablename__ = "research_deployment_workers"
    worker_id: str = Field(primary_key=True)
    mode: str
    build_hash: str
    interval_seconds: int
    cycle_timeout_seconds: int
    phase: str = "starting"
    account_key: str | None = Field(default=None,index=True)
    cycle_id: str | None = None
    job_id: str | None = None
    cycle_deadline: datetime | None = Field(default=None,sa_column=Column(UTCDateTime))
    last_result: dict[str,Any] | None = Field(default=None,sa_column=Column(JSON))
    started_at: datetime = Field(default_factory=now_utc,sa_column=Column(UTCDateTime,nullable=False))
    last_seen_at: datetime = Field(default_factory=now_utc,sa_column=Column(UTCDateTime,nullable=False))
