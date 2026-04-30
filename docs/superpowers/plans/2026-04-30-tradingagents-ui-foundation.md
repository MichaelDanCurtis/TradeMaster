# TradingAgents UI Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working TradingAgents web-app foundation: Python API, local persistence, normalized run events, a React/Next.js trading terminal shell, streamed fake runs, and approval-gated fake paper orders.

**Architecture:** Add a `tradingagents.ui` Python package beside the existing engine and a new `apps/web` frontend in the same repo. The first slice uses fake run events and a fake broker so the product surface, persistence model, and approval gates are real before wiring live LLM runs or Alpaca paper credentials. Later plans will replace fake run events with the existing `TradingAgentsGraph.stream(...)`, add CopilotKit/A2UI surfaces, and implement the Alpaca paper adapter.

**Tech Stack:** FastAPI, SQLModel/SQLite, Pydantic, pytest, Next.js, React, TypeScript, TradingView Lightweight Charts, native EventSource/SSE.

---

## Scope Boundary

This plan implements the first vertical slice only.

Included:

- Python API package and app entrypoint.
- SQLite persistence for runs, events, decisions, approvals, and fake broker orders.
- Normalized event schema for graph/run progress.
- Fake TradingAgents run stream for UI development.
- Fake broker adapter with approval-gated submission.
- Next.js app shell with watchlist, chart workspace, agent cockpit, decision ledger, and trade ticket.
- Tests for backend event, persistence, run, and broker behavior.

Deferred to follow-up plans:

- Real `TradingAgentsGraph` streaming adapter.
- CopilotKit and A2UI dynamic surfaces.
- A2A endpoint.
- Alpaca paper adapter.
- Full chart data from market vendors.
- Custom research-agent builder.

## File Structure

Backend files:

- Create `tradingagents/ui/__init__.py`: marks the UI API package.
- Create `tradingagents/ui/events.py`: Pydantic request/response and event schemas.
- Create `tradingagents/ui/db.py`: SQLModel engine/session initialization.
- Create `tradingagents/ui/models.py`: SQLModel tables.
- Create `tradingagents/ui/repository.py`: persistence operations with narrow methods.
- Create `tradingagents/ui/runner.py`: fake run stream and run lifecycle service.
- Create `tradingagents/ui/api.py`: FastAPI routes.
- Create `tradingagents/ui/__main__.py`: local API server entrypoint.
- Create `tradingagents/ui/brokers/__init__.py`: broker package exports.
- Create `tradingagents/ui/brokers/base.py`: broker protocol and value objects.
- Create `tradingagents/ui/brokers/fake.py`: fake paper broker implementation.
- Create `tradingagents/ui/brokers/service.py`: trade intent, approval, and submission orchestration.

Backend tests:

- Create `tests/ui/test_events.py`
- Create `tests/ui/test_repository.py`
- Create `tests/ui/test_runner.py`
- Create `tests/ui/test_broker_service.py`
- Create `tests/ui/test_api.py`

Project files:

- Modify `pyproject.toml`: add FastAPI, SQLModel, Uvicorn, pytest/httpx dev extra, and API script.
- Create `package.json`: root package scripts and frontend workspace.
- Create `apps/web/package.json`
- Create `apps/web/next.config.mjs`
- Create `apps/web/tsconfig.json`
- Create `apps/web/src/app/layout.tsx`
- Create `apps/web/src/app/page.tsx`
- Create `apps/web/src/app/globals.css`

Frontend files:

- Create `apps/web/src/lib/api.ts`: API client helpers and EventSource setup.
- Create `apps/web/src/lib/types.ts`: shared frontend types.
- Create `apps/web/src/data/watchlist.ts`: initial local watchlist.
- Create `apps/web/src/components/MarketShell.tsx`
- Create `apps/web/src/components/WatchlistRail.tsx`
- Create `apps/web/src/components/ChartWorkspace.tsx`
- Create `apps/web/src/components/AgentCockpit.tsx`
- Create `apps/web/src/components/RunTimeline.tsx`
- Create `apps/web/src/components/TradeTicket.tsx`

---

## Task 1: Backend Dependencies and API Package Skeleton

**Files:**

- Modify: `pyproject.toml`
- Create: `tradingagents/ui/__init__.py`
- Create: `tradingagents/ui/__main__.py`
- Create: `tradingagents/ui/api.py`
- Test: `tests/ui/test_api.py`

- [ ] **Step 1: Add failing health endpoint test**

Create `tests/ui/test_api.py`:

```python
from fastapi.testclient import TestClient

from tradingagents.ui.api import create_app


def test_health_endpoint_returns_ok():
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "tradingagents-ui"}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --with pytest --with httpx pytest tests/ui/test_api.py::test_health_endpoint_returns_ok -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.ui'`.

- [ ] **Step 3: Add backend dependencies and script**

Modify `pyproject.toml` dependencies to include:

```toml
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "sqlmodel>=0.0.22",
```

Add this optional dependency section below `[project.scripts]`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=9.0.0",
    "httpx>=0.28.0",
]
```

Add this script under `[project.scripts]`:

```toml
tradingagents-ui-api = "tradingagents.ui.__main__:main"
```

- [ ] **Step 4: Create API skeleton**

Create `tradingagents/ui/__init__.py`:

```python
"""Web UI API package for TradingAgents."""
```

Create `tradingagents/ui/api.py`:

```python
from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="TradingAgents UI API")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "tradingagents-ui"}

    return app
```

Create `tradingagents/ui/__main__.py`:

```python
import uvicorn

from tradingagents.ui.api import create_app


def main() -> None:
    uvicorn.run(create_app(), host="127.0.0.1", port=8787)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
uv run --extra dev pytest tests/ui/test_api.py::test_health_endpoint_returns_ok -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tradingagents/ui tests/ui/test_api.py
git commit -m "feat: add UI API skeleton"
```

---

## Task 2: Normalized Run Event Schemas

**Files:**

- Create: `tradingagents/ui/events.py`
- Test: `tests/ui/test_events.py`

- [ ] **Step 1: Add failing event schema tests**

Create `tests/ui/test_events.py`:

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tradingagents.ui.events import (
    RunConfig,
    RunCreated,
    RunEvent,
    RunStatus,
)


def test_run_config_defaults_to_safe_report_only_mode():
    config = RunConfig(ticker="nvda", trade_date="2026-04-30")

    assert config.ticker == "NVDA"
    assert config.trade_date == "2026-04-30"
    assert config.analysts == ["market", "social", "news", "fundamentals"]
    assert config.research_depth == 1
    assert config.broker_mode == "disabled"


def test_run_event_serializes_timestamp_as_iso_string():
    event = RunEvent(
        run_id="run_123",
        sequence=1,
        type="agent.started",
        node="Market Analyst",
        message="Started market analysis",
        payload={"ticker": "NVDA"},
        created_at=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
    )

    assert event.model_dump(mode="json")["created_at"] == "2026-04-30T12:00:00Z"


def test_run_event_rejects_unknown_event_type():
    with pytest.raises(ValidationError):
        RunEvent(
            run_id="run_123",
            sequence=1,
            type="unknown",
            node="Market Analyst",
            message="bad",
        )


def test_run_created_exposes_status():
    created = RunCreated(run_id="run_123", status=RunStatus.QUEUED)

    assert created.model_dump() == {"run_id": "run_123", "status": "queued"}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --extra dev pytest tests/ui/test_events.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.ui.events'`.

- [ ] **Step 3: Implement event schemas**

Create `tradingagents/ui/events.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AnalystKey = Literal["market", "social", "news", "fundamentals"]
BrokerMode = Literal["disabled", "paper", "live_preview"]
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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
uv run --extra dev pytest tests/ui/test_events.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/ui/events.py tests/ui/test_events.py
git commit -m "feat: define UI run event schemas"
```

---

## Task 3: SQLite Persistence Layer

**Files:**

- Create: `tradingagents/ui/db.py`
- Create: `tradingagents/ui/models.py`
- Create: `tradingagents/ui/repository.py`
- Test: `tests/ui/test_repository.py`

- [ ] **Step 1: Add failing repository tests**

Create `tests/ui/test_repository.py`:

```python
from pathlib import Path

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig, RunEvent
from tradingagents.ui.repository import UiRepository


def _repo(tmp_path: Path) -> UiRepository:
    db_url = f"sqlite:///{tmp_path / 'ui.db'}"
    engine, session_factory = create_session_factory(db_url)
    init_db(engine)
    return UiRepository(session_factory)


def test_create_run_and_list_runs(tmp_path):
    repo = _repo(tmp_path)
    config = RunConfig(ticker="NVDA", trade_date="2026-04-30")

    run = repo.create_run(config)
    runs = repo.list_runs()

    assert run.ticker == "NVDA"
    assert run.status == "queued"
    assert len(runs) == 1
    assert runs[0].run_id == run.run_id


def test_append_events_preserves_sequence(tmp_path):
    repo = _repo(tmp_path)
    run = repo.create_run(RunConfig(ticker="MSFT", trade_date="2026-04-30"))

    first = repo.append_event(
        RunEvent(run_id=run.run_id, sequence=1, type="run.started", message="Started")
    )
    second = repo.append_event(
        RunEvent(
            run_id=run.run_id,
            sequence=2,
            type="agent.started",
            node="Market Analyst",
            message="Market Analyst started",
        )
    )

    events = repo.list_events(run.run_id)

    assert [e.sequence for e in events] == [first.sequence, second.sequence]
    assert events[1].node == "Market Analyst"


def test_store_decision_updates_run_summary(tmp_path):
    repo = _repo(tmp_path)
    run = repo.create_run(RunConfig(ticker="AAPL", trade_date="2026-04-30"))

    decision = repo.store_decision(
        run_id=run.run_id,
        rating="Overweight",
        action="Buy",
        thesis="Momentum and fundamentals support a gradual build.",
        risk_notes="Size conservatively before earnings.",
    )
    summary = repo.get_run(run.run_id)

    assert decision.rating == "Overweight"
    assert summary.final_rating == "Overweight"
    assert summary.final_action == "Buy"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --extra dev pytest tests/ui/test_repository.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.ui.db'`.

- [ ] **Step 3: Implement database setup**

Create `tradingagents/ui/db.py`:

```python
from collections.abc import Generator

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine


def create_session_factory(database_url: str) -> tuple[Engine, type[Session]]:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)

    class BoundSession(Session):
        def __init__(self) -> None:
            super().__init__(engine)

    return engine, BoundSession


def init_db(engine: Engine) -> None:
    from tradingagents.ui import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def session_generator(session_factory: type[Session]) -> Generator[Session, None, None]:
    with session_factory() as session:
        yield session
```

- [ ] **Step 4: Implement SQLModel tables**

Create `tradingagents/ui/models.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def now_utc() -> datetime:
    return datetime.now(UTC)


class RunRecord(SQLModel, table=True):
    __tablename__ = "runs"

    run_id: str = Field(default_factory=lambda: new_id("run"), primary_key=True)
    ticker: str
    trade_date: str
    status: str = "queued"
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    final_rating: str | None = None
    final_action: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class RunEventRecord(SQLModel, table=True):
    __tablename__ = "run_events"

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True, foreign_key="runs.run_id")
    sequence: int
    type: str
    node: str | None = None
    message: str
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=now_utc)


class DecisionRecord(SQLModel, table=True):
    __tablename__ = "decisions"

    decision_id: str = Field(default_factory=lambda: new_id("decision"), primary_key=True)
    run_id: str = Field(index=True, foreign_key="runs.run_id")
    rating: str
    action: str
    thesis: str
    risk_notes: str
    created_at: datetime = Field(default_factory=now_utc)


class TradeIntentRecord(SQLModel, table=True):
    __tablename__ = "trade_intents"

    intent_id: str = Field(default_factory=lambda: new_id("intent"), primary_key=True)
    run_id: str = Field(index=True, foreign_key="runs.run_id")
    symbol: str
    side: str
    notional: float
    order_type: str = "market"
    status: str = "previewed"
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)


class ApprovalRecord(SQLModel, table=True):
    __tablename__ = "approvals"

    approval_id: str = Field(default_factory=lambda: new_id("approval"), primary_key=True)
    intent_id: str = Field(index=True, foreign_key="trade_intents.intent_id")
    actor: str
    action: str
    before_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    after_payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=now_utc)


class BrokerOrderRecord(SQLModel, table=True):
    __tablename__ = "broker_orders"

    order_id: str = Field(default_factory=lambda: new_id("order"), primary_key=True)
    intent_id: str = Field(index=True, foreign_key="trade_intents.intent_id")
    broker: str
    environment: str
    status: str
    broker_order_id: str
    created_at: datetime = Field(default_factory=now_utc)
```

- [ ] **Step 5: Implement repository**

Create `tradingagents/ui/repository.py`:

```python
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlmodel import Session, select

from tradingagents.ui.events import RunConfig, RunEvent
from tradingagents.ui.models import (
    ApprovalRecord,
    BrokerOrderRecord,
    DecisionRecord,
    RunEventRecord,
    RunRecord,
    TradeIntentRecord,
)


class UiRepository:
    def __init__(self, session_factory: type[Session]) -> None:
        self._session_factory = session_factory

    def create_run(self, config: RunConfig) -> RunRecord:
        with self._session_factory() as session:
            run = RunRecord(
                ticker=config.ticker,
                trade_date=config.trade_date,
                config=config.model_dump(mode="json"),
            )
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

    def get_run(self, run_id: str) -> RunRecord:
        with self._session_factory() as session:
            run = session.get(RunRecord, run_id)
            if run is None:
                raise KeyError(f"Run not found: {run_id}")
            return run

    def list_runs(self) -> list[RunRecord]:
        with self._session_factory() as session:
            statement = select(RunRecord).order_by(RunRecord.created_at.desc())
            return list(session.exec(statement).all())

    def set_run_status(self, run_id: str, status: str) -> RunRecord:
        with self._session_factory() as session:
            run = session.get(RunRecord, run_id)
            if run is None:
                raise KeyError(f"Run not found: {run_id}")
            run.status = status
            run.updated_at = datetime.now(UTC)
            session.add(run)
            session.commit()
            session.refresh(run)
            return run

    def append_event(self, event: RunEvent) -> RunEventRecord:
        with self._session_factory() as session:
            record = RunEventRecord(
                run_id=event.run_id,
                sequence=event.sequence,
                type=event.type,
                node=event.node,
                message=event.message,
                payload=event.payload,
                created_at=event.created_at,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def list_events(self, run_id: str) -> list[RunEventRecord]:
        with self._session_factory() as session:
            statement = (
                select(RunEventRecord)
                .where(RunEventRecord.run_id == run_id)
                .order_by(RunEventRecord.sequence)
            )
            return list(session.exec(statement).all())

    def store_decision(
        self,
        run_id: str,
        rating: str,
        action: str,
        thesis: str,
        risk_notes: str,
    ) -> DecisionRecord:
        with self._session_factory() as session:
            run = session.get(RunRecord, run_id)
            if run is None:
                raise KeyError(f"Run not found: {run_id}")
            decision = DecisionRecord(
                run_id=run_id,
                rating=rating,
                action=action,
                thesis=thesis,
                risk_notes=risk_notes,
            )
            run.final_rating = rating
            run.final_action = action
            run.updated_at = datetime.now(UTC)
            session.add(decision)
            session.add(run)
            session.commit()
            session.refresh(decision)
            return decision

    def create_trade_intent(
        self,
        run_id: str,
        symbol: str,
        side: str,
        notional: float,
        order_type: str = "market",
    ) -> TradeIntentRecord:
        with self._session_factory() as session:
            intent = TradeIntentRecord(
                run_id=run_id,
                symbol=symbol,
                side=side,
                notional=notional,
                order_type=order_type,
            )
            session.add(intent)
            session.commit()
            session.refresh(intent)
            return intent

    def get_trade_intent(self, intent_id: str) -> TradeIntentRecord:
        with self._session_factory() as session:
            intent = session.get(TradeIntentRecord, intent_id)
            if intent is None:
                raise KeyError(f"Trade intent not found: {intent_id}")
            return intent

    def record_approval(
        self,
        intent_id: str,
        actor: str,
        action: str,
        before_payload: dict,
        after_payload: dict,
    ) -> ApprovalRecord:
        with self._session_factory() as session:
            approval = ApprovalRecord(
                intent_id=intent_id,
                actor=actor,
                action=action,
                before_payload=before_payload,
                after_payload=after_payload,
            )
            session.add(approval)
            session.commit()
            session.refresh(approval)
            return approval

    def has_approval(self, intent_id: str, action: str = "approve_order") -> bool:
        with self._session_factory() as session:
            statement = (
                select(ApprovalRecord)
                .where(ApprovalRecord.intent_id == intent_id)
                .where(ApprovalRecord.action == action)
            )
            return session.exec(statement).first() is not None

    def store_broker_order(
        self,
        intent_id: str,
        broker: str,
        environment: str,
        status: str,
        broker_order_id: str,
    ) -> BrokerOrderRecord:
        with self._session_factory() as session:
            intent = session.get(TradeIntentRecord, intent_id)
            if intent is None:
                raise KeyError(f"Trade intent not found: {intent_id}")
            intent.status = status
            intent.updated_at = datetime.now(UTC)
            order = BrokerOrderRecord(
                intent_id=intent_id,
                broker=broker,
                environment=environment,
                status=status,
                broker_order_id=broker_order_id,
            )
            session.add(intent)
            session.add(order)
            session.commit()
            session.refresh(order)
            return order
```

- [ ] **Step 6: Run repository tests**

Run:

```bash
uv run --extra dev pytest tests/ui/test_repository.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradingagents/ui/db.py tradingagents/ui/models.py tradingagents/ui/repository.py tests/ui/test_repository.py
git commit -m "feat: add UI persistence layer"
```

---

## Task 4: Fake Run Service and Stream Contract

**Files:**

- Create: `tradingagents/ui/runner.py`
- Test: `tests/ui/test_runner.py`

- [ ] **Step 1: Add failing fake runner tests**

Create `tests/ui/test_runner.py`:

```python
import pytest

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import TradingRunService


@pytest.fixture()
def service(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    return TradingRunService(UiRepository(session_factory))


def test_start_fake_run_creates_run_and_events(service):
    created = service.start_run(RunConfig(ticker="NVDA", trade_date="2026-04-30"))

    events = service.list_events(created.run_id)

    assert created.status == "completed"
    assert [event.type for event in events] == [
        "run.created",
        "run.started",
        "agent.started",
        "tool.called",
        "report.updated",
        "agent.started",
        "decision.created",
        "trade.previewed",
        "run.completed",
    ]


def test_stream_events_returns_sse_payloads(service):
    created = service.start_run(RunConfig(ticker="AAPL", trade_date="2026-04-30"))

    chunks = list(service.stream_sse(created.run_id))

    assert chunks[0].startswith("event: run.created\n")
    assert '"ticker":"AAPL"' in "".join(chunks)
    assert chunks[-1].startswith("event: run.completed\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --extra dev pytest tests/ui/test_runner.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.ui.runner'`.

- [ ] **Step 3: Implement fake run service**

Create `tradingagents/ui/runner.py`:

```python
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime

from tradingagents.ui.events import RunConfig, RunCreated, RunEvent, RunStatus
from tradingagents.ui.models import RunEventRecord
from tradingagents.ui.repository import UiRepository


class TradingRunService:
    def __init__(self, repository: UiRepository) -> None:
        self._repo = repository

    def start_run(self, config: RunConfig) -> RunCreated:
        run = self._repo.create_run(config)
        self._append_fake_events(run.run_id, config)
        self._repo.store_decision(
            run_id=run.run_id,
            rating="Overweight",
            action="Buy",
            thesis=f"{config.ticker} has a constructive simulated setup for UI testing.",
            risk_notes="This is fake run output. Use paper trading only.",
        )
        self._repo.set_run_status(run.run_id, RunStatus.COMPLETED.value)
        return RunCreated(run_id=run.run_id, status=RunStatus.COMPLETED)

    def list_events(self, run_id: str) -> list[RunEventRecord]:
        return self._repo.list_events(run_id)

    def stream_sse(self, run_id: str) -> Iterable[str]:
        for record in self._repo.list_events(run_id):
            payload = {
                "run_id": record.run_id,
                "sequence": record.sequence,
                "type": record.type,
                "node": record.node,
                "message": record.message,
                "payload": record.payload,
                "created_at": record.created_at.isoformat().replace("+00:00", "Z"),
            }
            yield f"event: {record.type}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"

    def _append_fake_events(self, run_id: str, config: RunConfig) -> None:
        events = [
            ("run.created", None, f"Queued {config.ticker} analysis", {"ticker": config.ticker}),
            ("run.started", None, f"Started {config.ticker} analysis", {"trade_date": config.trade_date}),
            ("agent.started", "Market Analyst", "Market Analyst started", {}),
            ("tool.called", "Market Analyst", "Loaded simulated price and indicator data", {"tool": "get_stock_data"}),
            ("report.updated", "Market Analyst", "Market report updated", {"section": "market_report"}),
            ("agent.started", "Portfolio Manager", "Portfolio Manager started", {}),
            (
                "decision.created",
                "Portfolio Manager",
                "Final simulated decision created",
                {"rating": "Overweight", "action": "Buy"},
            ),
            (
                "trade.previewed",
                "Broker",
                "Paper trade preview is available",
                {"side": "buy", "notional": 1000.0},
            ),
            ("run.completed", None, "Run completed", {"status": "completed"}),
        ]
        for index, (event_type, node, message, payload) in enumerate(events, start=1):
            self._repo.append_event(
                RunEvent(
                    run_id=run_id,
                    sequence=index,
                    type=event_type,  # type: ignore[arg-type]
                    node=node,
                    message=message,
                    payload=payload,
                    created_at=datetime.now(UTC),
                )
            )
```

- [ ] **Step 4: Run fake runner tests**

Run:

```bash
uv run --extra dev pytest tests/ui/test_runner.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/ui/runner.py tests/ui/test_runner.py
git commit -m "feat: add fake UI run stream"
```

---

## Task 5: Run API Endpoints

**Files:**

- Modify: `tradingagents/ui/api.py`
- Modify: `tradingagents/ui/__main__.py`
- Test: `tests/ui/test_api.py`

- [ ] **Step 1: Extend API tests**

Replace `tests/ui/test_api.py` with:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from tradingagents.ui.api import create_app


def test_health_endpoint_returns_ok(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "tradingagents-ui"}


def test_create_run_and_fetch_events(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "disabled"},
    )
    run_id = created.json()["run_id"]
    events = client.get(f"/api/runs/{run_id}/events")

    assert created.status_code == 200
    assert created.json()["status"] == "completed"
    assert events.status_code == 200
    assert events.json()[0]["type"] == "run.created"


def test_stream_run_events_as_sse(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "AAPL", "trade_date": "2026-04-30"},
    ).json()["run_id"]

    response = client.get(f"/api/runs/{run_id}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: run.created" in response.text
    assert "event: run.completed" in response.text
```

- [ ] **Step 2: Run tests to verify new endpoints fail**

Run:

```bash
uv run --extra dev pytest tests/ui/test_api.py -v
```

Expected: FAIL with 404 for `/api/runs`.

- [ ] **Step 3: Implement API dependencies and routes**

Replace `tradingagents/ui/api.py` with:

```python
from __future__ import annotations

import os
from collections.abc import Generator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig, RunCreated
from tradingagents.ui.models import RunEventRecord
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import TradingRunService


def create_app(database_url: str | None = None) -> FastAPI:
    db_url = database_url or os.getenv(
        "TRADINGAGENTS_UI_DATABASE_URL",
        "sqlite:///./.tradingagents-ui.db",
    )
    engine, session_factory = create_session_factory(db_url)
    init_db(engine)

    app = FastAPI(title="TradingAgents UI API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def repository() -> UiRepository:
        return UiRepository(session_factory)

    def run_service(repo: UiRepository = Depends(repository)) -> TradingRunService:
        return TradingRunService(repo)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "tradingagents-ui"}

    @app.post("/api/runs", response_model=RunCreated)
    def create_run(
        config: RunConfig,
        service: TradingRunService = Depends(run_service),
    ) -> RunCreated:
        return service.start_run(config)

    @app.get("/api/runs/{run_id}/events")
    def list_events(
        run_id: str,
        service: TradingRunService = Depends(run_service),
    ) -> list[RunEventRecord]:
        return service.list_events(run_id)

    @app.get("/api/runs/{run_id}/stream")
    def stream_events(
        run_id: str,
        service: TradingRunService = Depends(run_service),
    ) -> StreamingResponse:
        return StreamingResponse(
            service.stream_sse(run_id),
            media_type="text/event-stream",
        )

    return app
```

Replace `tradingagents/ui/__main__.py` with:

```python
import uvicorn


def main() -> None:
    uvicorn.run(
        "tradingagents.ui.api:create_app",
        factory=True,
        host="127.0.0.1",
        port=8787,
        reload=False,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run API tests**

Run:

```bash
uv run --extra dev pytest tests/ui/test_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/ui/api.py tradingagents/ui/__main__.py tests/ui/test_api.py
git commit -m "feat: expose UI run API"
```

---

## Task 6: Fake Broker and Approval Gate

**Files:**

- Create: `tradingagents/ui/brokers/__init__.py`
- Create: `tradingagents/ui/brokers/base.py`
- Create: `tradingagents/ui/brokers/fake.py`
- Create: `tradingagents/ui/brokers/service.py`
- Test: `tests/ui/test_broker_service.py`

- [ ] **Step 1: Add failing broker service tests**

Create `tests/ui/test_broker_service.py`:

```python
from pathlib import Path

import pytest

from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.brokers.service import BrokerService
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig
from tradingagents.ui.repository import UiRepository


def _service(tmp_path: Path) -> tuple[BrokerService, UiRepository, str]:
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    run = repo.create_run(RunConfig(ticker="NVDA", trade_date="2026-04-30", broker_mode="paper"))
    return BrokerService(repo, FakePaperBroker()), repo, run.run_id


def test_create_trade_preview_records_intent(tmp_path):
    service, repo, run_id = _service(tmp_path)

    preview = service.preview_order(run_id=run_id, symbol="NVDA", side="buy", notional=1000)

    intent = repo.get_trade_intent(preview.intent_id)
    assert preview.environment == "paper"
    assert intent.status == "previewed"


def test_submit_order_requires_approval(tmp_path):
    service, _, run_id = _service(tmp_path)
    preview = service.preview_order(run_id=run_id, symbol="NVDA", side="buy", notional=1000)

    with pytest.raises(PermissionError, match="requires approval"):
        service.submit_approved_order(preview.intent_id)


def test_approved_order_submits_to_fake_broker(tmp_path):
    service, repo, run_id = _service(tmp_path)
    preview = service.preview_order(run_id=run_id, symbol="NVDA", side="buy", notional=1000)

    service.approve_order(preview.intent_id, actor="local-user")
    order = service.submit_approved_order(preview.intent_id)

    assert order.environment == "paper"
    assert order.status == "submitted"
    assert order.broker_order_id.startswith("fake_order_")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --extra dev pytest tests/ui/test_broker_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.ui.brokers'`.

- [ ] **Step 3: Implement broker value objects and protocol**

Create `tradingagents/ui/brokers/__init__.py`:

```python
"""Broker adapters for TradingAgents UI."""
```

Create `tradingagents/ui/brokers/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Literal


OrderSide = Literal["buy", "sell"]


@dataclass(frozen=True)
class OrderPreview:
    intent_id: str
    broker: str
    environment: str
    symbol: str
    side: OrderSide
    notional: float
    estimated_price: float
    estimated_quantity: float


@dataclass(frozen=True)
class BrokerOrder:
    intent_id: str
    broker: str
    environment: str
    status: str
    broker_order_id: str


class BrokerAdapter(Protocol):
    broker_name: str
    environment: str

    def estimate_price(self, symbol: str) -> float:
        ...

    def submit_order(self, intent_id: str, symbol: str, side: OrderSide, notional: float) -> BrokerOrder:
        ...
```

- [ ] **Step 4: Implement fake broker**

Create `tradingagents/ui/brokers/fake.py`:

```python
from __future__ import annotations

from uuid import uuid4

from tradingagents.ui.brokers.base import BrokerOrder, OrderSide


class FakePaperBroker:
    broker_name = "fake"
    environment = "paper"

    def estimate_price(self, symbol: str) -> float:
        return {
            "NVDA": 900.0,
            "AAPL": 190.0,
            "MSFT": 420.0,
            "SPY": 520.0,
        }.get(symbol.upper(), 100.0)

    def submit_order(self, intent_id: str, symbol: str, side: OrderSide, notional: float) -> BrokerOrder:
        return BrokerOrder(
            intent_id=intent_id,
            broker=self.broker_name,
            environment=self.environment,
            status="submitted",
            broker_order_id=f"fake_order_{uuid4().hex[:12]}",
        )
```

- [ ] **Step 5: Implement broker service**

Create `tradingagents/ui/brokers/service.py`:

```python
from __future__ import annotations

from tradingagents.ui.brokers.base import BrokerAdapter, BrokerOrder, OrderPreview, OrderSide
from tradingagents.ui.repository import UiRepository


class BrokerService:
    def __init__(self, repository: UiRepository, broker: BrokerAdapter) -> None:
        self._repo = repository
        self._broker = broker

    def preview_order(self, run_id: str, symbol: str, side: OrderSide, notional: float) -> OrderPreview:
        if notional <= 0:
            raise ValueError("notional must be greater than zero")
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol must not be empty")
        intent = self._repo.create_trade_intent(
            run_id=run_id,
            symbol=symbol,
            side=side,
            notional=notional,
        )
        estimated_price = self._broker.estimate_price(symbol)
        return OrderPreview(
            intent_id=intent.intent_id,
            broker=self._broker.broker_name,
            environment=self._broker.environment,
            symbol=symbol,
            side=side,
            notional=notional,
            estimated_price=estimated_price,
            estimated_quantity=round(notional / estimated_price, 6),
        )

    def approve_order(self, intent_id: str, actor: str) -> None:
        intent = self._repo.get_trade_intent(intent_id)
        self._repo.record_approval(
            intent_id=intent_id,
            actor=actor,
            action="approve_order",
            before_payload={"status": intent.status},
            after_payload={"status": "approved"},
        )

    def submit_approved_order(self, intent_id: str) -> BrokerOrder:
        if not self._repo.has_approval(intent_id):
            raise PermissionError("order submission requires approval")
        intent = self._repo.get_trade_intent(intent_id)
        order = self._broker.submit_order(
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            side=intent.side,  # type: ignore[arg-type]
            notional=intent.notional,
        )
        self._repo.store_broker_order(
            intent_id=order.intent_id,
            broker=order.broker,
            environment=order.environment,
            status=order.status,
            broker_order_id=order.broker_order_id,
        )
        return order
```

- [ ] **Step 6: Run broker tests**

Run:

```bash
uv run --extra dev pytest tests/ui/test_broker_service.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tradingagents/ui/brokers tests/ui/test_broker_service.py
git commit -m "feat: add approval-gated fake broker"
```

---

## Task 7: Trade Ticket API Endpoints

**Files:**

- Modify: `tradingagents/ui/api.py`
- Test: `tests/ui/test_api.py`

- [ ] **Step 1: Add failing trade API test**

Append to `tests/ui/test_api.py`:

```python
def test_trade_ticket_preview_approval_and_submit(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "paper"},
    ).json()["run_id"]

    preview = client.post(
        "/api/trades/preview",
        json={"run_id": run_id, "symbol": "NVDA", "side": "buy", "notional": 1000},
    )
    intent_id = preview.json()["intent_id"]
    blocked_submit = client.post(f"/api/trades/{intent_id}/submit")
    approval = client.post(f"/api/trades/{intent_id}/approve", json={"actor": "local-user"})
    submitted = client.post(f"/api/trades/{intent_id}/submit")

    assert preview.status_code == 200
    assert preview.json()["environment"] == "paper"
    assert blocked_submit.status_code == 403
    assert approval.status_code == 200
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
```

- [ ] **Step 2: Run API tests to verify trade endpoints fail**

Run:

```bash
uv run --extra dev pytest tests/ui/test_api.py -v
```

Expected: FAIL with 404 for `/api/trades/preview`.

- [ ] **Step 3: Add trade API models and routes**

In `tradingagents/ui/api.py`, add imports:

```python
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.brokers.service import BrokerService
```

Add request models near `create_app`:

```python
class TradePreviewRequest(BaseModel):
    run_id: str
    symbol: str
    side: Literal["buy", "sell"]
    notional: float = Field(gt=0)


class ApprovalRequest(BaseModel):
    actor: str = "local-user"
```

Inside `create_app`, add dependency:

```python
    def broker_service(repo: UiRepository = Depends(repository)) -> BrokerService:
        return BrokerService(repo, FakePaperBroker())
```

Inside `create_app`, add routes:

```python
    @app.post("/api/trades/preview")
    def preview_trade(
        request: TradePreviewRequest,
        service: BrokerService = Depends(broker_service),
    ):
        return service.preview_order(
            run_id=request.run_id,
            symbol=request.symbol,
            side=request.side,
            notional=request.notional,
        )

    @app.post("/api/trades/{intent_id}/approve")
    def approve_trade(
        intent_id: str,
        request: ApprovalRequest,
        service: BrokerService = Depends(broker_service),
    ) -> dict[str, str]:
        service.approve_order(intent_id, actor=request.actor)
        return {"intent_id": intent_id, "status": "approved"}

    @app.post("/api/trades/{intent_id}/submit")
    def submit_trade(
        intent_id: str,
        service: BrokerService = Depends(broker_service),
    ):
        try:
            return service.submit_approved_order(intent_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
```

- [ ] **Step 4: Run API tests**

Run:

```bash
uv run --extra dev pytest tests/ui/test_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/ui/api.py tests/ui/test_api.py
git commit -m "feat: expose fake trade ticket API"
```

---

## Task 8: Frontend App Scaffold

**Files:**

- Create: `package.json`
- Create: `apps/web/package.json`
- Create: `apps/web/next.config.mjs`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/src/app/layout.tsx`
- Create: `apps/web/src/app/page.tsx`
- Create: `apps/web/src/app/globals.css`

- [ ] **Step 1: Create package files**

Create root `package.json`:

```json
{
  "private": true,
  "workspaces": [
    "apps/web"
  ],
  "scripts": {
    "web:dev": "npm --workspace apps/web run dev",
    "web:build": "npm --workspace apps/web run build",
    "web:lint": "npm --workspace apps/web run lint"
  }
}
```

Create `apps/web/package.json`:

```json
{
  "name": "tradingagents-ui-web",
  "private": true,
  "version": "0.1.0",
  "scripts": {
    "dev": "next dev --hostname 127.0.0.1 --port 3000",
    "build": "next build",
    "lint": "next lint"
  },
  "dependencies": {
    "lightweight-charts": "^4.2.3",
    "next": "^15.3.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@types/node": "^22.14.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "eslint": "^9.24.0",
    "eslint-config-next": "^15.3.0",
    "typescript": "^5.8.0"
  }
}
```

- [ ] **Step 2: Create Next config and TypeScript config**

Create `apps/web/next.config.mjs`:

```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true
};

export default nextConfig;
```

Create `apps/web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "es2022"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Create minimal app page**

Create `apps/web/src/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TradingAgents UI",
  description: "Local trading research terminal for TradingAgents"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

Create `apps/web/src/app/page.tsx`:

```tsx
export default function Page() {
  return <main className="app-shell">TradingAgents UI</main>;
}
```

Create `apps/web/src/app/globals.css`:

```css
:root {
  color-scheme: dark;
  background: #0b0f14;
  color: #e6edf3;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-height: 100vh;
  background: #0b0f14;
}

button,
input,
select {
  font: inherit;
}

.app-shell {
  min-height: 100vh;
  padding: 24px;
}
```

- [ ] **Step 4: Install frontend dependencies**

Run:

```bash
npm install
```

Expected: creates `package-lock.json` and installs dependencies.

- [ ] **Step 5: Build frontend**

Run:

```bash
npm run web:build
```

Expected: PASS with Next.js production build output.

- [ ] **Step 6: Commit**

```bash
git add package.json package-lock.json apps/web
git commit -m "feat: scaffold TradingAgents web app"
```

---

## Task 9: Frontend API Types and Trading Terminal Shell

**Files:**

- Create: `apps/web/src/lib/types.ts`
- Create: `apps/web/src/lib/api.ts`
- Create: `apps/web/src/data/watchlist.ts`
- Create: `apps/web/src/components/MarketShell.tsx`
- Create: `apps/web/src/components/WatchlistRail.tsx`
- Create: `apps/web/src/components/ChartWorkspace.tsx`
- Modify: `apps/web/src/app/page.tsx`
- Modify: `apps/web/src/app/globals.css`

- [ ] **Step 1: Add frontend types**

Create `apps/web/src/lib/types.ts`:

```ts
export type RunStatus = "queued" | "running" | "completed" | "failed" | "canceled";
export type BrokerMode = "disabled" | "paper" | "live_preview";
export type OrderSide = "buy" | "sell";

export type WatchlistItem = {
  symbol: string;
  name: string;
  price: number;
  changePercent: number;
};

export type RunCreated = {
  run_id: string;
  status: RunStatus;
};

export type RunEvent = {
  run_id: string;
  sequence: number;
  type: string;
  node: string | null;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type OrderPreview = {
  intent_id: string;
  broker: string;
  environment: string;
  symbol: string;
  side: OrderSide;
  notional: number;
  estimated_price: number;
  estimated_quantity: number;
};
```

- [ ] **Step 2: Add API client**

Create `apps/web/src/lib/api.ts`:

```ts
import type { BrokerMode, OrderPreview, OrderSide, RunCreated, RunEvent } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8787";

export async function createRun(input: {
  ticker: string;
  tradeDate: string;
  brokerMode: BrokerMode;
}): Promise<RunCreated> {
  const response = await fetch(`${API_BASE}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ticker: input.ticker,
      trade_date: input.tradeDate,
      broker_mode: input.brokerMode
    })
  });
  if (!response.ok) {
    throw new Error(`Failed to create run: ${response.status}`);
  }
  return response.json();
}

export async function listRunEvents(runId: string): Promise<RunEvent[]> {
  const response = await fetch(`${API_BASE}/api/runs/${runId}/events`);
  if (!response.ok) {
    throw new Error(`Failed to list run events: ${response.status}`);
  }
  return response.json();
}

export function openRunEventSource(runId: string): EventSource {
  return new EventSource(`${API_BASE}/api/runs/${runId}/stream`);
}

export async function previewTrade(input: {
  runId: string;
  symbol: string;
  side: OrderSide;
  notional: number;
}): Promise<OrderPreview> {
  const response = await fetch(`${API_BASE}/api/trades/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      run_id: input.runId,
      symbol: input.symbol,
      side: input.side,
      notional: input.notional
    })
  });
  if (!response.ok) {
    throw new Error(`Failed to preview trade: ${response.status}`);
  }
  return response.json();
}
```

- [ ] **Step 3: Add watchlist and shell components**

Create `apps/web/src/data/watchlist.ts`:

```ts
import type { WatchlistItem } from "@/lib/types";

export const WATCHLIST: WatchlistItem[] = [
  { symbol: "NVDA", name: "NVIDIA", price: 900.12, changePercent: 1.84 },
  { symbol: "AAPL", name: "Apple", price: 190.44, changePercent: -0.32 },
  { symbol: "MSFT", name: "Microsoft", price: 420.09, changePercent: 0.67 },
  { symbol: "SPY", name: "S&P 500 ETF", price: 520.16, changePercent: 0.21 }
];
```

Create `apps/web/src/components/WatchlistRail.tsx`:

```tsx
"use client";

import type { WatchlistItem } from "@/lib/types";

export function WatchlistRail({
  items,
  selectedSymbol,
  onSelect
}: {
  items: WatchlistItem[];
  selectedSymbol: string;
  onSelect: (symbol: string) => void;
}) {
  return (
    <aside className="watchlist-rail" aria-label="Watchlist">
      <div className="rail-header">Watchlist</div>
      {items.map((item) => (
        <button
          className={item.symbol === selectedSymbol ? "watchlist-item selected" : "watchlist-item"}
          key={item.symbol}
          onClick={() => onSelect(item.symbol)}
          type="button"
        >
          <span>
            <strong>{item.symbol}</strong>
            <small>{item.name}</small>
          </span>
          <span className={item.changePercent >= 0 ? "positive" : "negative"}>
            {item.changePercent >= 0 ? "+" : ""}
            {item.changePercent.toFixed(2)}%
          </span>
        </button>
      ))}
    </aside>
  );
}
```

Create `apps/web/src/components/ChartWorkspace.tsx`:

```tsx
"use client";

import { useEffect, useRef } from "react";
import { createChart, ColorType } from "lightweight-charts";

export function ChartWorkspace({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: "#0f1720" },
        textColor: "#d8e1ea"
      },
      grid: {
        vertLines: { color: "#1f2a35" },
        horzLines: { color: "#1f2a35" }
      },
      rightPriceScale: { borderColor: "#2b3745" },
      timeScale: { borderColor: "#2b3745" }
    });
    const series = chart.addCandlestickSeries({
      upColor: "#2fbf71",
      downColor: "#f05d5e",
      borderVisible: false,
      wickUpColor: "#2fbf71",
      wickDownColor: "#f05d5e"
    });
    series.setData([
      { time: "2026-04-24", open: 880, high: 902, low: 871, close: 895 },
      { time: "2026-04-25", open: 895, high: 910, low: 888, close: 904 },
      { time: "2026-04-28", open: 904, high: 918, low: 899, close: 912 },
      { time: "2026-04-29", open: 912, high: 920, low: 893, close: 900 },
      { time: "2026-04-30", open: 900, high: 930, low: 896, close: 924 }
    ]);
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [symbol]);

  return (
    <section className="chart-workspace">
      <header className="workspace-header">
        <div>
          <h1>{symbol}</h1>
          <p>Simulated chart data for the first UI slice</p>
        </div>
      </header>
      <div ref={containerRef} className="chart-surface" />
    </section>
  );
}
```

Create `apps/web/src/components/MarketShell.tsx`:

```tsx
"use client";

import { useState } from "react";

import { WATCHLIST } from "@/data/watchlist";
import { ChartWorkspace } from "@/components/ChartWorkspace";
import { WatchlistRail } from "@/components/WatchlistRail";

export function MarketShell() {
  const [selectedSymbol, setSelectedSymbol] = useState(WATCHLIST[0].symbol);

  return (
    <main className="market-shell">
      <WatchlistRail items={WATCHLIST} selectedSymbol={selectedSymbol} onSelect={setSelectedSymbol} />
      <ChartWorkspace symbol={selectedSymbol} />
      <aside className="agent-rail">Agent cockpit</aside>
    </main>
  );
}
```

- [ ] **Step 4: Wire page and styles**

Replace `apps/web/src/app/page.tsx`:

```tsx
import { MarketShell } from "@/components/MarketShell";

export default function Page() {
  return <MarketShell />;
}
```

Append to `apps/web/src/app/globals.css`:

```css
.market-shell {
  display: grid;
  grid-template-columns: 280px minmax(520px, 1fr) 360px;
  min-height: 100vh;
  background: #0b0f14;
}

.watchlist-rail,
.agent-rail {
  border-right: 1px solid #202b36;
  background: #0d131a;
  padding: 16px;
}

.agent-rail {
  border-left: 1px solid #202b36;
  border-right: 0;
}

.rail-header {
  margin-bottom: 12px;
  color: #91a4b7;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}

.watchlist-item {
  display: flex;
  justify-content: space-between;
  width: 100%;
  min-height: 64px;
  margin-bottom: 8px;
  padding: 12px;
  color: #e6edf3;
  background: #111923;
  border: 1px solid #23303d;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
}

.watchlist-item.selected {
  border-color: #4f8cff;
  background: #142033;
}

.watchlist-item small {
  display: block;
  margin-top: 4px;
  color: #8ea1b3;
}

.positive {
  color: #2fbf71;
}

.negative {
  color: #f05d5e;
}

.chart-workspace {
  min-width: 0;
  padding: 18px;
}

.workspace-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 16px;
}

.workspace-header h1 {
  margin: 0;
  font-size: 28px;
}

.workspace-header p {
  margin: 4px 0 0;
  color: #8ea1b3;
}

.chart-surface {
  height: 420px;
  border: 1px solid #202b36;
  border-radius: 8px;
  overflow: hidden;
}
```

- [ ] **Step 5: Build frontend**

Run:

```bash
npm run web:build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src
git commit -m "feat: add trading terminal shell"
```

---

## Task 10: Agent Cockpit and Run Streaming UI

**Files:**

- Create: `apps/web/src/components/AgentCockpit.tsx`
- Create: `apps/web/src/components/RunTimeline.tsx`
- Modify: `apps/web/src/components/MarketShell.tsx`
- Modify: `apps/web/src/app/globals.css`

- [ ] **Step 1: Add run timeline component**

Create `apps/web/src/components/RunTimeline.tsx`:

```tsx
import type { RunEvent } from "@/lib/types";

export function RunTimeline({ events }: { events: RunEvent[] }) {
  return (
    <div className="run-timeline">
      {events.length === 0 ? (
        <p className="muted">No run events yet.</p>
      ) : (
        events.map((event) => (
          <article className="timeline-event" key={`${event.run_id}-${event.sequence}`}>
            <div className="event-type">{event.type}</div>
            <div className="event-message">{event.message}</div>
            {event.node ? <div className="event-node">{event.node}</div> : null}
          </article>
        ))
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add agent cockpit**

Create `apps/web/src/components/AgentCockpit.tsx`:

```tsx
"use client";

import { useState } from "react";

import { createRun, listRunEvents, previewTrade } from "@/lib/api";
import type { OrderPreview, RunEvent } from "@/lib/types";
import { RunTimeline } from "@/components/RunTimeline";

export function AgentCockpit({ symbol }: { symbol: string }) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [preview, setPreview] = useState<OrderPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  async function startRun() {
    setError(null);
    setPreview(null);
    setIsRunning(true);
    try {
      const created = await createRun({
        ticker: symbol,
        tradeDate: new Date().toISOString().slice(0, 10),
        brokerMode: "paper"
      });
      setRunId(created.run_id);
      const nextEvents = await listRunEvents(created.run_id);
      setEvents(nextEvents);
      const tradePreview = await previewTrade({
        runId: created.run_id,
        symbol,
        side: "buy",
        notional: 1000
      });
      setPreview(tradePreview);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Run failed");
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <aside className="agent-cockpit">
      <header>
        <span>Agent Cockpit</span>
        <strong>{symbol}</strong>
      </header>
      <button className="primary-button" type="button" onClick={startRun} disabled={isRunning}>
        {isRunning ? "Running..." : "Run report"}
      </button>
      {runId ? <p className="muted">Run: {runId}</p> : null}
      {error ? <p className="error">{error}</p> : null}
      <RunTimeline events={events} />
      {preview ? (
        <section className="trade-preview">
          <h2>Paper trade preview</h2>
          <p>
            {preview.side.toUpperCase()} {preview.symbol} ${preview.notional.toLocaleString()}
          </p>
          <p className="muted">
            Est. {preview.estimated_quantity} shares at ${preview.estimated_price}
          </p>
        </section>
      ) : null}
    </aside>
  );
}
```

- [ ] **Step 3: Replace the static rail with the cockpit**

Modify `apps/web/src/components/MarketShell.tsx` to import and render the cockpit:

```tsx
"use client";

import { useState } from "react";

import { WATCHLIST } from "@/data/watchlist";
import { AgentCockpit } from "@/components/AgentCockpit";
import { ChartWorkspace } from "@/components/ChartWorkspace";
import { WatchlistRail } from "@/components/WatchlistRail";

export function MarketShell() {
  const [selectedSymbol, setSelectedSymbol] = useState(WATCHLIST[0].symbol);

  return (
    <main className="market-shell">
      <WatchlistRail items={WATCHLIST} selectedSymbol={selectedSymbol} onSelect={setSelectedSymbol} />
      <ChartWorkspace symbol={selectedSymbol} />
      <AgentCockpit symbol={selectedSymbol} />
    </main>
  );
}
```

- [ ] **Step 4: Add cockpit styles**

Append to `apps/web/src/app/globals.css`:

```css
.agent-cockpit {
  border-left: 1px solid #202b36;
  background: #0d131a;
  padding: 16px;
  overflow-y: auto;
}

.agent-cockpit header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 16px;
}

.primary-button {
  width: 100%;
  min-height: 42px;
  color: #ffffff;
  background: #2563eb;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.primary-button:disabled {
  cursor: wait;
  opacity: 0.7;
}

.muted {
  color: #8ea1b3;
  font-size: 13px;
}

.error {
  color: #f05d5e;
}

.run-timeline {
  margin-top: 16px;
}

.timeline-event,
.trade-preview {
  margin-bottom: 10px;
  padding: 12px;
  background: #111923;
  border: 1px solid #23303d;
  border-radius: 6px;
}

.event-type {
  color: #8fb7ff;
  font-size: 12px;
  font-weight: 700;
}

.event-message {
  margin-top: 4px;
}

.event-node {
  margin-top: 6px;
  color: #8ea1b3;
  font-size: 12px;
}

.trade-preview h2 {
  margin: 0 0 8px;
  font-size: 16px;
}
```

- [ ] **Step 5: Build frontend**

Run:

```bash
npm run web:build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src
git commit -m "feat: stream fake run into agent cockpit"
```

---

## Task 11: Approval Buttons and Fake Order Submission UI

**Files:**

- Modify: `apps/web/src/lib/api.ts`
- Create: `apps/web/src/components/TradeTicket.tsx`
- Modify: `apps/web/src/components/AgentCockpit.tsx`
- Modify: `apps/web/src/app/globals.css`

- [ ] **Step 1: Add trade approval API helpers**

Append to `apps/web/src/lib/api.ts`:

```ts
export async function approveTrade(intentId: string): Promise<{ intent_id: string; status: string }> {
  const response = await fetch(`${API_BASE}/api/trades/${intentId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor: "local-user" })
  });
  if (!response.ok) {
    throw new Error(`Failed to approve trade: ${response.status}`);
  }
  return response.json();
}

export async function submitTrade(intentId: string): Promise<{
  intent_id: string;
  broker: string;
  environment: string;
  status: string;
  broker_order_id: string;
}> {
  const response = await fetch(`${API_BASE}/api/trades/${intentId}/submit`, {
    method: "POST"
  });
  if (!response.ok) {
    throw new Error(`Failed to submit trade: ${response.status}`);
  }
  return response.json();
}
```

- [ ] **Step 2: Add trade ticket component**

Create `apps/web/src/components/TradeTicket.tsx`:

```tsx
"use client";

import { useState } from "react";

import { approveTrade, submitTrade } from "@/lib/api";
import type { OrderPreview } from "@/lib/types";

export function TradeTicket({ preview }: { preview: OrderPreview }) {
  const [status, setStatus] = useState("previewed");
  const [brokerOrderId, setBrokerOrderId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function approveAndSubmit() {
    setError(null);
    try {
      await approveTrade(preview.intent_id);
      const order = await submitTrade(preview.intent_id);
      setStatus(order.status);
      setBrokerOrderId(order.broker_order_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Trade submission failed");
    }
  }

  return (
    <section className="trade-ticket">
      <div className="mode-pill">Paper trading</div>
      <h2>Trade ticket</h2>
      <dl>
        <div>
          <dt>Symbol</dt>
          <dd>{preview.symbol}</dd>
        </div>
        <div>
          <dt>Side</dt>
          <dd>{preview.side.toUpperCase()}</dd>
        </div>
        <div>
          <dt>Notional</dt>
          <dd>${preview.notional.toLocaleString()}</dd>
        </div>
        <div>
          <dt>Estimated quantity</dt>
          <dd>{preview.estimated_quantity}</dd>
        </div>
      </dl>
      <button className="primary-button" type="button" onClick={approveAndSubmit} disabled={status === "submitted"}>
        {status === "submitted" ? "Submitted" : "Approve paper order"}
      </button>
      {brokerOrderId ? <p className="muted">Broker order: {brokerOrderId}</p> : null}
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
```

- [ ] **Step 3: Use trade ticket in cockpit**

Modify `apps/web/src/components/AgentCockpit.tsx`:

```tsx
import { TradeTicket } from "@/components/TradeTicket";
```

Replace the existing `<section className="trade-preview">...</section>` block with:

```tsx
      {preview ? <TradeTicket preview={preview} /> : null}
```

- [ ] **Step 4: Add trade ticket styles**

Append to `apps/web/src/app/globals.css`:

```css
.trade-ticket {
  margin-top: 16px;
  padding: 12px;
  background: #111923;
  border: 1px solid #33512f;
  border-radius: 6px;
}

.mode-pill {
  display: inline-flex;
  margin-bottom: 8px;
  padding: 3px 8px;
  color: #b8f7ca;
  background: #173321;
  border: 1px solid #2c6a3f;
  border-radius: 999px;
  font-size: 12px;
}

.trade-ticket h2 {
  margin: 0 0 10px;
  font-size: 16px;
}

.trade-ticket dl {
  margin: 0 0 12px;
}

.trade-ticket dl div {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid #22303c;
}

.trade-ticket dt {
  color: #8ea1b3;
}

.trade-ticket dd {
  margin: 0;
}
```

- [ ] **Step 5: Build frontend**

Run:

```bash
npm run web:build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src
git commit -m "feat: add paper trade approval UI"
```

---

## Task 12: End-to-End Local Smoke Verification

**Files:**

- No source files required.

- [ ] **Step 1: Run backend tests**

Run:

```bash
uv run --extra dev pytest tests/ui tests/test_signal_processing.py tests/test_model_validation.py -v
```

Expected: PASS.

- [ ] **Step 2: Run full existing Python test suite**

Run:

```bash
uv run --extra dev pytest
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```bash
npm run web:build
```

Expected: PASS.

- [ ] **Step 4: Start API server**

Run:

```bash
uv run --extra dev tradingagents-ui-api
```

Expected: API listens at `http://127.0.0.1:8787`.

- [ ] **Step 5: In another terminal, verify API health**

Run:

```bash
curl -s http://127.0.0.1:8787/api/health
```

Expected:

```json
{"status":"ok","service":"tradingagents-ui"}
```

- [ ] **Step 6: Start frontend**

Run:

```bash
npm run web:dev
```

Expected: Next.js app listens at `http://127.0.0.1:3000`.

- [ ] **Step 7: Manual smoke path**

Open `http://127.0.0.1:3000` and verify:

- Watchlist renders.
- Clicking a symbol updates the chart header.
- Clicking `Run report` populates timeline events.
- A paper trade ticket appears.
- Clicking `Approve paper order` changes status to submitted and displays a fake broker order id.

- [ ] **Step 8: Commit verification-only cleanup if needed**

If any lockfiles or generated config files changed from install/build commands, inspect them. Commit only intentional package lock or source changes:

```bash
git status --short
git diff --stat
```

Expected: no unreviewed generated artifacts other than intended package-lock updates.

---

## Follow-Up Plans After This Foundation

1. Real TradingAgents runner adapter:
   - Map `TradingAgentsGraph.graph.stream(...)` chunks to `RunEvent`.
   - Persist report sections and final decisions from real runs.
   - Preserve checkpoint mode.

2. CopilotKit/A2UI right rail:
   - Add component registry.
   - Render agent progress/report/trade-ticket surfaces through declarative payloads.
   - Keep stable app shell outside agent control.

3. Alpaca paper adapter:
   - Add paper-only credential config.
   - Implement account, position, preview, submit, status, and cancel.
   - Keep live execution absent.

4. A2A endpoint:
   - Expose agent card.
   - Wrap run lifecycle as task states.
   - Publish report/trade artifacts.

## Plan Self-Review Notes

- Spec coverage: This plan covers the stable app shell, local API, persistence, normalized run events, fake paper trade approvals, and report/run UI foundation. It intentionally defers real TradingAgents streaming, A2UI/CopilotKit, A2A, Alpaca, and custom builder to follow-up plans.
- Scope check: The full v1 design is multiple subsystems. This first plan produces working, testable software by itself and avoids mixing real broker credentials or dynamic agent UI into the foundation.
- Safety check: No live broker submit method is introduced. The only executable broker path is fake paper order submission after explicit approval.
