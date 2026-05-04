from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AnalystKey = Literal["market", "social", "news", "fundamentals"]
BrokerMode = Literal["disabled", "paper", "live_preview"]
ExecutionMode = Literal["simulated", "real"]
RunEventType = Literal[
    "run.created",
    "run.started",
    "agent.started",
    "tool.called",
    "report.updated",
    "decision.created",
    "trade.previewed",
    "run.completed",
    "run.failed",
]


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class RunConfig(BaseModel):
    ticker: str
    trade_date: str
    analysts: list[AnalystKey] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )
    research_depth: int = Field(default=1, ge=1, le=5)
    llm_provider: str = "openai"
    quick_model: str = "gpt-5.4-mini"
    deep_model: str = "gpt-5.4"
    checkpoint: bool = False
    broker_mode: BrokerMode = "disabled"
    execution_mode: ExecutionMode = "simulated"

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        ticker = value.strip().upper()
        if not ticker:
            raise ValueError("ticker must not be empty")
        return ticker


class RunCreated(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    run_id: str
    status: RunStatus


class RunEvent(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    run_id: str
    sequence: int = Field(ge=1)
    type: RunEventType
    node: str | None = None
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RunSummary(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    run_id: str
    ticker: str
    trade_date: str
    status: RunStatus
    final_rating: str | None = None
    final_action: str | None = None
    created_at: datetime
    updated_at: datetime
