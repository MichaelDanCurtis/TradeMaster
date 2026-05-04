from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import TradingRunService


def test_simulated_run_creates_completed_observability_trace(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repository = UiRepository(session_factory)
    service = TradingRunService(repository)

    created = service.start_run(
        RunConfig(
            ticker="NVDA",
            trade_date="2026-04-30",
            broker_mode="paper",
            execution_mode="simulated",
            llm_provider="openai",
            quick_model="gpt-5.4-mini",
            deep_model="gpt-5.4",
        )
    )
    trace = repository.get_observability_trace(created.run_id)

    assert trace.run_id == created.run_id
    assert trace.status == "completed"
    assert trace.provider == "local"
    assert trace.external_trace_id is None
    assert trace.metadata_payload["ticker"] == "NVDA"
    assert trace.metadata_payload["execution_mode"] == "simulated"
    assert trace.metadata_payload["llm_provider"] == "openai"
    assert trace.metadata_payload["quick_model"] == "gpt-5.4-mini"
    assert trace.metadata_payload["deep_model"] == "gpt-5.4"


def test_real_run_without_runner_marks_observability_trace_failed(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repository = UiRepository(session_factory)
    service = TradingRunService(repository)

    created = service.start_run(
        RunConfig(
            ticker="NVDA",
            trade_date="2026-04-30",
            execution_mode="real",
        )
    )
    trace = repository.get_observability_trace(created.run_id)

    assert trace.status == "failed"
    assert trace.metadata_payload["failure_reason"] == "real_runner_not_configured"
