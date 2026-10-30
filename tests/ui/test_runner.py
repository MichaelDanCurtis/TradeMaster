import pytest
from sqlmodel import select

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig, RunEvent
from tradingagents.ui.models import TradeIntentRecord
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import RealRunResult, TradingRunService


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
        RunConfig(ticker="NVDA", trade_date="2026-04-30", broker_mode="paper", execution_mode="simulated")
    )

    events = service.list_events(created.run_id)

    assert created.status == "completed"
    assert [event.node for event in events if event.type == "agent.started"] == [
        "Market Analyst",
        "News Analyst",
        "Social Analyst",
        "Fundamentals Analyst",
        "Research Manager",
        "Risk Manager",
        "Portfolio Manager",
    ]
    assert [event.type for event in events][-3:] == [
        "decision.created",
        "trade.previewed",
        "run.completed",
    ]
    market_tool = next(event for event in events if event.node == "Market Analyst" and event.type == "tool.called")
    assert market_tool.payload["provider"] == "simulated-market-data"


def test_real_completion_event_publishes_only_after_final_trace(service_and_session_factory, monkeypatch):
    _, sessions = service_and_session_factory
    repository = UiRepository(sessions)
    append = repository.append_event
    observed = []
    def inspect_at_publication(event):
        if event.type == "run.completed":
            trace = repository.get_observability_trace(event.run_id)
            observed.append(trace.metadata_payload.get("final_action"))
        return append(event)
    monkeypatch.setattr(repository, "append_event", inspect_at_publication)
    service = TradingRunService(repository, real_runner=lambda *_: RealRunResult(events=[], rating="Neutral", action="Hold", thesis="Synthetic ordering check"))
    result = service.start_run(RunConfig(ticker="TEST", trade_date="2026-04-30", execution_mode="real", broker_mode="disabled"))
    assert result.status == "completed"
    assert observed == ["Hold"]


def test_disabled_fake_run_does_not_create_trade_preview_or_intent(
    service_and_session_factory,
):
    service, session_factory = service_and_session_factory

    created = service.start_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", broker_mode="disabled", execution_mode="simulated")
    )

    events = service.list_events(created.run_id)
    with session_factory() as session:
        intents = session.exec(select(TradeIntentRecord)).all()
    assert "trade.previewed" not in [event.type for event in events]
    assert intents == []


def test_real_run_without_runner_fails_without_fake_agent_events(service):
    created = service.start_run(
        RunConfig(
            ticker="NVDA",
            trade_date="2026-04-30",
            execution_mode="real",
        )
    )

    events = service.list_events(created.run_id)

    assert created.status == "failed"
    assert [event.type for event in events] == [
        "run.created",
        "run.started",
        "run.failed",
    ]
    assert events[-1].payload == {
        "status": "failed",
        "reason": "real_runner_not_configured",
    }


def test_real_run_with_runner_persists_normalized_events_and_decision(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repository = UiRepository(session_factory)

    class RecordingRealRunner:
        def __init__(self) -> None:
            self.config: RunConfig | None = None

        def __call__(self, run_id: str, config: RunConfig) -> RealRunResult:
            self.config = config
            return RealRunResult(
                events=[
                    RunEvent(
                        run_id=run_id,
                        sequence=99,
                        type="agent.started",
                        node="Market Analyst",
                        message="Market Analyst started.",
                    ),
                    RunEvent(
                        run_id=run_id,
                        sequence=100,
                        type="decision.created",
                        node="Portfolio Manager",
                        message="Created real TradingAgents decision.",
                        payload={"rating": "Neutral", "action": "Hold"},
                    ),
                ],
                rating="Neutral",
                action="Hold",
                thesis="Real graph result was normalized into the UI event contract.",
                risk_notes="No broker order was submitted.",
            )

    real_runner = RecordingRealRunner()
    service = TradingRunService(repository, real_runner=real_runner)

    created = service.start_run(
        RunConfig(
            ticker="NVDA",
            trade_date="2026-04-30",
            execution_mode="real",
        )
    )
    events = service.list_events(created.run_id)
    run = repository.get_run(created.run_id)

    assert created.status == "completed"
    assert real_runner.config is not None
    assert real_runner.config.ticker == "NVDA"
    assert [event.sequence for event in events] == [1, 2, 3, 4, 5]
    assert [event.type for event in events] == [
        "run.created",
        "run.started",
        "agent.started",
        "decision.created",
        "run.completed",
    ]
    assert run.final_rating == "Neutral"
    assert run.final_action == "Hold"


def test_queue_real_run_returns_running_before_runner_executes(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repository = UiRepository(session_factory)

    class RecordingRealRunner:
        called = False

        def __call__(self, run_id: str, config: RunConfig) -> RealRunResult:
            self.called = True
            return RealRunResult(
                events=[],
                rating="Neutral",
                action="Hold",
                thesis="Queued real run completed.",
            )

    real_runner = RecordingRealRunner()
    service = TradingRunService(repository, real_runner=real_runner)

    created = service.queue_real_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", execution_mode="real")
    )
    events = service.list_events(created.run_id)
    run = repository.get_run(created.run_id)

    assert created.status == "running"
    assert run.status == "running"
    assert real_runner.called is False
    assert [event.type for event in events][:2] == ["run.created", "run.started"]
    assert [event.node for event in events if event.type == "agent.started"] == [
        "Market Analyst",
        "News Analyst",
        "Social Analyst",
        "Fundamentals Analyst",
        "Bull Researcher",
        "Bear Researcher",
        "Research Manager",
        "Trader",
        "Risk Manager",
        "Portfolio Manager",
    ]

    service.complete_queued_real_run(
        created.run_id,
        RunConfig(ticker="NVDA", trade_date="2026-04-30", execution_mode="real"),
    )

    assert real_runner.called is True
    assert repository.get_run(created.run_id).status == "completed"


def test_queue_real_run_labels_safe_synthesis_runner_without_full_graph_claim(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repository = UiRepository(session_factory)

    service = TradingRunService(
        repository,
        real_runner=lambda run_id, config: RealRunResult([], "Hold", "Hold", "Done."),
    )

    created = service.queue_real_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", execution_mode="real")
    )
    events = service.list_events(created.run_id)

    progress_messages = [event.message for event in events if event.type == "agent.started"]
    progress_sources = [event.payload["source"] for event in events if event.type == "agent.started"]
    assert progress_messages
    assert all("safe synthesis runner" in message for message in progress_messages)
    assert all("full TradingAgents graph" not in message for message in progress_messages)
    assert progress_sources
    assert all(source == "safe-synthesis-runner" for source in progress_sources)


def test_queue_real_run_labels_full_graph_runner_when_configured(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repository = UiRepository(session_factory)

    class TradingAgentsGraphRunner:
        def __call__(self, run_id: str, config: RunConfig) -> RealRunResult:
            return RealRunResult([], "Hold", "Hold", "Done.")

    service = TradingRunService(repository, real_runner=TradingAgentsGraphRunner())

    created = service.queue_real_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", execution_mode="real")
    )
    events = service.list_events(created.run_id)

    progress_messages = [event.message for event in events if event.type == "agent.started"]
    progress_sources = [event.payload["source"] for event in events if event.type == "agent.started"]
    assert progress_messages
    assert all("full TradingAgents graph" in message for message in progress_messages)
    assert progress_sources
    assert all(source == "tradingagents-graph" for source in progress_sources)


def test_queue_real_run_only_queues_selected_analysts_and_downstream_team(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repository = UiRepository(session_factory)

    service = TradingRunService(repository, real_runner=lambda run_id, config: RealRunResult([], "Hold", "Hold", "Done."))

    created = service.queue_real_run(
        RunConfig(
            ticker="NVDA",
            trade_date="2026-04-30",
            execution_mode="real",
            analysts=["market"],
        )
    )

    events = service.list_events(created.run_id)

    assert [event.node for event in events if event.type == "agent.started"] == [
        "Market Analyst",
        "Bull Researcher",
        "Bear Researcher",
        "Research Manager",
        "Trader",
        "Risk Manager",
        "Portfolio Manager",
    ]


def test_fail_interrupted_runs_marks_leftover_running_runs_failed(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repository = UiRepository(session_factory)
    service = TradingRunService(repository, real_runner=lambda run_id, config: RealRunResult([], "Hold", "Hold", "Done."))

    created = service.queue_real_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", execution_mode="real")
    )

    failed_count = service.fail_interrupted_runs(reason="server_restart")
    run = repository.get_run(created.run_id)
    events = service.list_events(created.run_id)

    assert failed_count == 1
    assert run.status == "failed"
    assert events[-1].type == "run.failed"
    assert events[-1].message == "Run was interrupted before completion."
    assert events[-1].payload == {
        "status": "failed",
        "reason": "server_restart",
    }


def test_real_run_records_failed_event_when_runner_raises(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repository = UiRepository(session_factory)

    class FailingRealRunner:
        def __call__(self, run_id: str, config: RunConfig) -> RealRunResult:
            raise RuntimeError("missing provider credentials")

    service = TradingRunService(repository, real_runner=FailingRealRunner())

    created = service.start_run(
        RunConfig(
            ticker="NVDA",
            trade_date="2026-04-30",
            execution_mode="real",
        )
    )
    events = service.list_events(created.run_id)
    run = repository.get_run(created.run_id)

    assert created.status == "failed"
    assert run.status == "failed"
    assert [event.type for event in events] == [
        "run.created",
        "run.started",
        "run.failed",
    ]
    assert events[-1].payload["reason"] == "real_runner_exception"
    assert events[-1].payload["error"] == "missing provider credentials"


def test_stream_events_returns_sse_payloads(service):
    import asyncio

    created = service.start_run(
        RunConfig(ticker="AAPL", trade_date="2026-04-30", execution_mode="simulated")
    )

    async def _drain() -> list[str]:
        out: list[str] = []
        # poll_interval=0 closes the stream the instant the run.completed
        # event is read; start_run is synchronous so all events are already
        # persisted by the time we ask for them.
        async for chunk in service.stream_sse(
            created.run_id, poll_interval=0, heartbeat_every=1000
        ):
            out.append(chunk)
        return out

    chunks = asyncio.run(_drain())

    assert chunks[0].startswith("event: run.created\n")
    assert '"ticker":"AAPL"' in "".join(chunks)
    assert chunks[-1].startswith("event: run.completed\n")
