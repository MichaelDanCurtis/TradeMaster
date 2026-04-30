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
