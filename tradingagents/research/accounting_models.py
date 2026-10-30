from datetime import datetime
from typing import Any

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from tradingagents.ui.models import UTCDateTime, new_id, now_utc
from tradingagents.research.accounting_storage import AccountingReportJSON


class PaperBaselineRecord(SQLModel, table=True):
    __tablename__ = "paper_account_baselines"
    baseline_id: str = Field(default_factory=lambda:new_id("pab"), primary_key=True)
    account_key: str = Field(index=True)
    content_hash: str
    snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    state: str = "previewed"
    expires_at: datetime = Field(sa_column=Column(UTCDateTime, nullable=False))
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class PaperEnrollmentRecord(SQLModel, table=True):
    __tablename__ = "paper_account_enrollments"
    account_key: str = Field(primary_key=True)
    baseline_id: str = Field(foreign_key="paper_account_baselines.baseline_id", unique=True)
    provider_id: str
    account_id: str
    actor: str
    approved_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class PaperAccountActivityRecord(SQLModel, table=True):
    __tablename__ = "paper_account_activities"
    __table_args__ = (UniqueConstraint("account_key", "source_id"),)
    activity_key: str = Field(primary_key=True)
    account_key: str = Field(foreign_key="paper_account_enrollments.account_key", index=True)
    source_id: str
    content_hash: str
    activity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    first_observed_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class PaperActivityRevisionRecord(SQLModel, table=True):
    __tablename__ = "paper_activity_revisions"
    revision_key: str = Field(primary_key=True)
    account_key: str = Field(index=True)
    source_id: str
    previous_hash: str
    revised_hash: str
    activity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    observed_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class PaperReconciliationRecord(SQLModel, table=True):
    __tablename__ = "paper_account_reconciliations"
    reconciliation_id: str = Field(default_factory=lambda:new_id("par"), primary_key=True)
    content_hash: str = Field(unique=True)
    account_key: str = Field(foreign_key="paper_account_enrollments.account_key", index=True)
    request: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    report: dict[str, Any] = Field(sa_column=Column(AccountingReportJSON(), nullable=False))
    observed_at: datetime = Field(sa_column=Column(UTCDateTime, nullable=False))
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class PaperCorrectionReviewRecord(SQLModel, table=True):
    __tablename__ = "paper_correction_reviews"
    review_id: str = Field(default_factory=lambda:new_id("pcr"), primary_key=True)
    account_key: str = Field(foreign_key="paper_account_enrollments.account_key", index=True)
    content_hash: str
    state_hash: str
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    expires_at: datetime = Field(sa_column=Column(UTCDateTime, nullable=False))
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class PaperCorrectionApprovalRecord(SQLModel, table=True):
    __tablename__ = "paper_correction_approvals"
    correction_id: str = Field(default_factory=lambda:new_id("pca"), primary_key=True)
    review_id: str = Field(foreign_key="paper_correction_reviews.review_id", unique=True)
    account_key: str = Field(index=True)
    actor: str
    reason: str
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))
