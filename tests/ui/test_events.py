from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tradingagents.ui.events import (
    RunConfig,
    RunCreated,
    RunEvent,
    RunStatus,
)


def test_run_config_defaults_to_real_research_with_broker_disabled():
    config = RunConfig(ticker="nvda", trade_date="2026-04-30")

    assert config.ticker == "NVDA"
    assert config.trade_date == "2026-04-30"
    assert config.analysts == ["market", "social", "news", "fundamentals"]
    assert config.research_depth == 1
    assert config.broker_mode == "disabled"
    assert config.execution_mode == "real"


def test_run_event_serializes_timestamp_as_iso_string():
    event = RunEvent(
        run_id="run_123",
        sequence=1,
        type="agent.started",
        node="Market Analyst",
        message="Started market analysis",
        payload={"ticker": "NVDA"},
        created_at=datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc),
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
