import pytest
from sqlmodel import select

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig
from tradingagents.ui.models import TradeIntentRecord
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import TradingRunService


@pytest.fixture()
def service_and_session_factory(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    return TradingRunService(UiRepository(session_factory)), session_factory


@pytest.fixture()
def service(service_and_session_factory):
    return service_and_session_factory[0]


def test_start_fake_run_creates_run_and_events(service):
    created = service.start_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", broker_mode="paper")
    )

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


def test_disabled_fake_run_does_not_create_trade_preview_or_intent(
    service_and_session_factory,
):
    service, session_factory = service_and_session_factory

    created = service.start_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", broker_mode="disabled")
    )

    events = service.list_events(created.run_id)
    with session_factory() as session:
        intents = session.exec(select(TradeIntentRecord)).all()
    assert "trade.previewed" not in [event.type for event in events]
    assert intents == []


def test_stream_events_returns_sse_payloads(service):
    created = service.start_run(RunConfig(ticker="AAPL", trade_date="2026-04-30"))

    chunks = list(service.stream_sse(created.run_id))

    assert chunks[0].startswith("event: run.created\n")
    assert '"ticker":"AAPL"' in "".join(chunks)
    assert chunks[-1].startswith("event: run.completed\n")
