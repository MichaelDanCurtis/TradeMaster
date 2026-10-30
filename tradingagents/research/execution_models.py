from datetime import datetime
from typing import Any

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel

from tradingagents.ui.models import UTCDateTime, new_id, now_utc


class PaperExecutionAccountRecord(SQLModel, table=True):
    __tablename__ = "paper_execution_accounts"
    account_key: str = Field(primary_key=True)
    provider_id: str
    account_id: str
    writer_attempt_id: str | None = None
    last_execution_at: datetime | None = Field(default=None, sa_column=Column(UTCDateTime))
    snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class ExactPaperOrderRecord(SQLModel, table=True):
    __tablename__ = "paper_exact_orders"
    order_id: str = Field(default_factory=lambda: new_id("po"), primary_key=True)
    intent_id: str = Field(foreign_key="ui_trade_intents.intent_id", unique=True)
    account_key: str = Field(foreign_key="paper_execution_accounts.account_key", index=True)
    deployment_id: str | None = Field(default=None, index=True)
    target_id: str | None = None
    content_hash: str
    order: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    policy: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    preview_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    state: str = "previewed"
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class PaperExecutionAttemptRecord(SQLModel, table=True):
    __tablename__ = "paper_execution_attempts"
    attempt_id: str = Field(default_factory=lambda: new_id("pea"), primary_key=True)
    order_id: str = Field(foreign_key="paper_exact_orders.order_id", unique=True)
    account_key: str = Field(foreign_key="paper_execution_accounts.account_key", index=True)
    client_order_id: str = Field(unique=True)
    approval_id: str
    state: str = "dispatching"
    filled_quantity: str = "0"
    broker_order_id: str | None = None
    observation: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))
    updated_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))


class PaperReservationRecord(SQLModel, table=True):
    __tablename__ = "paper_execution_reservations"
    attempt_id: str = Field(foreign_key="paper_execution_attempts.attempt_id", primary_key=True)
    account_key: str = Field(index=True)
    symbol: str
    side: str
    risk_group: str | None = None
    quantity: str
    price_usd: str
    fee_usd: str
    active: bool = True


class PaperExecutionEventRecord(SQLModel, table=True):
    __tablename__ = "paper_execution_events"
    event_id: str = Field(default_factory=lambda: new_id("pee"), primary_key=True)
    order_id: str = Field(foreign_key="paper_exact_orders.order_id", index=True)
    attempt_id: str | None = Field(default=None, index=True)
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=now_utc, sa_column=Column(UTCDateTime, nullable=False))
