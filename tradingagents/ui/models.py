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
