from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig
from tradingagents.ui.observability import ObservabilityService
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import TradingRunService
from tradingagents.ui.secrets import EnvSecretStore


class FakeLangfuseObservation:
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self.updates: list[dict[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.created_trace_seed: str | None = None
        self.observations: list[dict[str, object]] = []
        self.last_observation: FakeLangfuseObservation | None = None
        self.flushed = False

    def create_trace_id(self, seed: str) -> str:
        self.created_trace_seed = seed
        return "0123456789abcdef0123456789abcdef"

    def start_as_current_observation(self, **kwargs):
        self.observations.append(kwargs)
        self.last_observation = FakeLangfuseObservation(
            kwargs["trace_context"]["trace_id"]
        )
        return self.last_observation

    def get_trace_url(self, *, trace_id: str) -> str:
        return f"https://cloud.langfuse.com/project/local/traces/{trace_id}"

    def flush(self) -> None:
        self.flushed = True


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


def test_observability_service_exports_run_trace_to_langfuse(tmp_path, monkeypatch):
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
        )
    )
    repository.upsert_provider_config(
        "langfuse-observability",
        enabled=True,
        secret_ref="env:TRADEMASTER_LANGFUSE_CREDS",
    )
    monkeypatch.setenv(
        "TRADEMASTER_LANGFUSE_CREDS",
        '{"public_key":"pk-lf-local","secret_key":"sk-lf-local","base_url":"https://cloud.langfuse.com"}',
    )
    fake_client = FakeLangfuseClient()
    observability = ObservabilityService(
        repository,
        secret_store_factory=lambda _: EnvSecretStore(),
        langfuse_client_factory=lambda credentials: fake_client,
    )

    exported = observability.export_run_trace(created.run_id)

    assert exported.provider == "langfuse-observability"
    assert exported.status == "exported"
    assert exported.external_trace_id == "0123456789abcdef0123456789abcdef"
    assert exported.metadata_payload["external_trace_url"].endswith(
        "/traces/0123456789abcdef0123456789abcdef"
    )
    assert exported.metadata_payload["exported_to"] == "langfuse"
    assert exported.metadata_payload["export_status"] == "exported"
    assert "sk-lf-local" not in str(exported.metadata_payload)
    assert fake_client.created_trace_seed == created.run_id
    assert len(fake_client.observations) == 1
    observation = fake_client.observations[0]
    assert observation["as_type"] == "span"
    assert observation["name"] == "tradingagents.run"
    assert observation["input"] == {
        "run_id": created.run_id,
        "ticker": "NVDA",
        "trade_date": "2026-04-30",
    }
    assert observation["trace_context"] == {
        "trace_id": "0123456789abcdef0123456789abcdef",
        "parent_span_id": "0123456789abcdef",
    }
    assert observation["metadata"] | {
        "trace_id": exported.trace_id,
        "run_id": created.run_id,
        "ticker": "NVDA",
        "trade_date": "2026-04-30",
        "broker_mode": "paper",
        "execution_mode": "simulated",
        "llm_provider": "openai",
        "quick_model": "gpt-5-mini",
        "deep_model": "gpt-5",
        "local_status": "completed",
    } == observation["metadata"]
    assert fake_client.last_observation is not None
    assert fake_client.last_observation.updates == [
        {
            "output": {
                "status": "completed",
                "final_action": "Buy",
                "final_rating": "Overweight",
            },
            "level": "DEFAULT",
            "status_message": "TradingAgents run completed",
        }
    ]
    assert fake_client.flushed is True
    events = repository.list_private_office_events()
    assert events[-1].event_type == "observability.trace_exported"
    assert events[-1].actor == "Observability"
    assert events[-1].entity_id == created.run_id
    assert events[-1].payload == {
        "run_id": created.run_id,
        "provider_id": "langfuse-observability",
        "external_trace_id": "0123456789abcdef0123456789abcdef",
        "external_trace_url": "https://cloud.langfuse.com/project/local/traces/0123456789abcdef0123456789abcdef",
    }


def test_observability_service_requires_enabled_langfuse_provider(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repository = UiRepository(session_factory)
    created = TradingRunService(repository).start_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30")
    )
    observability = ObservabilityService(repository)

    try:
        observability.export_run_trace(created.run_id)
    except PermissionError as exc:
        assert str(exc) == "LangFuse observability is disabled or missing a secret_ref"
    else:
        raise AssertionError("expected missing LangFuse provider configuration to fail")
