from datetime import datetime
from typing import Any
from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel
from tradingagents.ui.models import UTCDateTime, new_id, now_utc


class ExecutionSchedule(SQLModel, table=True):
    __tablename__ = "execution_schedules"
    schedule_id: str = Field(default_factory=lambda: new_id("schedule"), primary_key=True)
    idempotency_key: str = Field(unique=True)
    request_hash: str
    content_hash: str
    account_key: str = Field(index=True)
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    state: str = Field(default="previewed", index=True)
    revision: int = 1
    message: str = "Review every exact child order before approval"
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))
    approved_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime))
    review_expires_at: datetime = Field(sa_column=Column(UTCDateTime, nullable=False))


class ScheduledLeg(SQLModel, table=True):
    __tablename__ = "execution_schedule_legs"
    leg_id: str = Field(default_factory=lambda: new_id("slice"), primary_key=True)
    schedule_id: str = Field(foreign_key="execution_schedules.schedule_id", index=True)
    order_id: str = Field(foreign_key="paper_exact_orders.order_id", unique=True)
    ordinal: int
    due_at: datetime = Field(sa_column=Column(UTCDateTime, nullable=False))
    expires_at: datetime = Field(sa_column=Column(UTCDateTime, nullable=False))


class ScheduleEvent(SQLModel, table=True):
    __tablename__ = "execution_schedule_events"
    event_id: str = Field(default_factory=lambda: new_id("schedule_event"), primary_key=True)
    schedule_id: str = Field(foreign_key="execution_schedules.schedule_id", index=True)
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class SchedulerWorker(SQLModel, table=True):
    __tablename__ = "execution_scheduler_workers"
    worker_id: str = Field(primary_key=True)
    state: str = "idle"
    last_seen_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))
    result: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
