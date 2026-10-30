from datetime import timedelta
from pathlib import Path

import pytest

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


def test_persisted_run_timestamps_remain_utc_aware(tmp_path):
    repo = _repo(tmp_path)
    run = repo.create_run(RunConfig(ticker="TSLA", trade_date="2026-04-30"))

    reread = repo.get_run(run.run_id)

    assert reread.created_at.tzinfo is not None
    assert reread.created_at.utcoffset() == timedelta(0)
    assert reread.updated_at.tzinfo is not None
    assert reread.updated_at.utcoffset() == timedelta(0)


def test_create_and_mark_report_schedule_run(tmp_path):
    repo = _repo(tmp_path)
    schedule = repo.create_report_schedule(
        name="NVDA opening stance",
        symbol="NVDA",
        cadence="market_open",
        broker_mode="disabled",
        execution_mode="real",
        enabled=True,
        payload={"window": "market-open"},
    )
    run = repo.create_run(RunConfig(ticker="NVDA", trade_date="2026-05-06"))

    updated = repo.mark_report_schedule_run(schedule.schedule_id, run.run_id)
    schedules = repo.list_report_schedules(symbol="nvda")

    assert schedule.symbol == "NVDA"
    assert schedule.enabled is True
    assert updated.last_run_id == run.run_id
    assert updated.last_ran_at is not None
    assert schedules[0].schedule_id == schedule.schedule_id


def test_research_runner_mode_defaults_and_persists(tmp_path):
    repo = _repo(tmp_path)

    assert repo.get_research_runner_mode() == "llm-ui-runner"

    updated = repo.set_research_runner_mode("tradingagents-graph-runner")

    assert updated.value["mode"] == "tradingagents-graph-runner"
    assert repo.get_research_runner_mode() == "tradingagents-graph-runner"


def test_research_runner_mode_rejects_unknown_values(tmp_path):
    repo = _repo(tmp_path)

    try:
        repo.set_research_runner_mode("unknown-runner")
    except ValueError as exc:
        assert "research runner mode" in str(exc)
    else:
        raise AssertionError("unknown research runner mode should fail")


def test_developer_mode_defaults_to_off_and_persists(tmp_path):
    repo = _repo(tmp_path)

    assert repo.get_developer_mode_enabled() is False

    repo.set_developer_mode_enabled(True)
    assert repo.get_developer_mode_enabled() is True

    repo.set_developer_mode_enabled(False)
    assert repo.get_developer_mode_enabled() is False


def test_create_user_provider_records_openai_compatible_endpoint(tmp_path):
    repo = _repo(tmp_path)

    record = repo.create_user_provider(
        name="Z.AI GLM",
        kind="openai-compatible",
        base_url="https://api.z.ai/api/paas/v4/",
        model="glm-4.6",
        api_key_env="env:ZHIPU_API_KEY",
        role_models={"coordinator": "glm-4.6", "agent": "glm-4-air", "overrides": {}},
    )

    assert record.provider_id == "user:z-ai-glm"
    assert record.role == "llm"
    assert record.status == "needs_key"
    assert record.enabled is False
    assert record.secret_ref == "env:ZHIPU_API_KEY"
    assert record.config["user_defined"] is True
    assert record.config["kind"] == "openai-compatible"
    assert record.config["provider"] == "openai-compatible"
    assert record.config["base_url"] == "https://api.z.ai/api/paas/v4/"
    assert record.config["model"] == "glm-4.6"
    assert record.config["auth_required"] is True
    assert record.config["graph_runner_supported"] is True
    assert record.config["role_models"]["coordinator"] == "glm-4.6"
    assert "openai-compatible" in record.capabilities
    assert "user-defined" in record.capabilities


def test_create_user_provider_anthropic_kind_routes_to_anthropic_factory(tmp_path):
    repo = _repo(tmp_path)

    record = repo.create_user_provider(
        name="Custom Claude Gateway",
        kind="anthropic-compatible",
        base_url="https://my-claude-proxy.example.com",
        model="claude-internal-1",
    )

    # No api_key_env -> anonymous (suitable for local proxies)
    assert record.config["auth_required"] is False
    assert record.config["kind"] == "anthropic-compatible"
    # The factory identifier is plain "anthropic" so AnthropicClient
    # picks it up; the "anthropic-compatible" tag is preserved in the
    # public capability list for UI display.
    assert record.config["provider"] == "anthropic"
    assert "anthropic-compatible" in record.capabilities


def test_create_user_provider_rejects_invalid_input(tmp_path):
    repo = _repo(tmp_path)

    with pytest.raises(ValueError, match="name is required"):
        repo.create_user_provider(
            name="   ", kind="openai-compatible", base_url="https://x", model="m"
        )
    with pytest.raises(ValueError, match="provider kind"):
        repo.create_user_provider(
            name="X", kind="grpc", base_url="https://x", model="m"
        )
    with pytest.raises(ValueError, match="base_url is required"):
        repo.create_user_provider(
            name="X", kind="openai-compatible", base_url="", model="m"
        )
    with pytest.raises(ValueError, match="model is required"):
        repo.create_user_provider(
            name="X", kind="openai-compatible", base_url="https://x", model=""
        )
    with pytest.raises(ValueError, match="alphanumeric"):
        repo.create_user_provider(
            name="!!!", kind="openai-compatible", base_url="https://x", model="m"
        )


def test_create_user_provider_rejects_duplicate_name(tmp_path):
    repo = _repo(tmp_path)
    repo.create_user_provider(
        name="GLM", kind="openai-compatible", base_url="https://x", model="m"
    )

    with pytest.raises(ValueError, match="already exists"):
        repo.create_user_provider(
            name="glm",  # different case -> same slug
            kind="openai-compatible",
            base_url="https://y",
            model="m",
        )


def test_delete_user_provider_removes_record(tmp_path):
    repo = _repo(tmp_path)
    record = repo.create_user_provider(
        name="Kimi", kind="openai-compatible", base_url="https://x", model="m"
    )

    repo.delete_user_provider(record.provider_id)

    ids = {p.provider_id for p in repo.list_provider_configs()}
    assert record.provider_id not in ids


def test_delete_user_provider_refuses_built_in(tmp_path):
    repo = _repo(tmp_path)

    with pytest.raises(ValueError, match="only user-defined"):
        repo.delete_user_provider("openai-codex-oauth-llm")


def test_delete_user_provider_refuses_when_bound_to_role(tmp_path):
    repo = _repo(tmp_path)
    record = repo.create_user_provider(
        name="GLM", kind="openai-compatible", base_url="https://x", model="m"
    )
    repo.upsert_provider_role_assignment("research_llm", provider_id=record.provider_id)

    with pytest.raises(ValueError, match="bound to roles"):
        repo.delete_user_provider(record.provider_id)


def test_upsert_provider_config_preserves_user_defined_marker(tmp_path):
    repo = _repo(tmp_path)
    record = repo.create_user_provider(
        name="GLM", kind="openai-compatible", base_url="https://old", model="m"
    )

    # Caller updates config without echoing back user_defined: True
    updated = repo.upsert_provider_config(
        record.provider_id,
        config={
            "kind": "openai-compatible",
            "provider": "openai-compatible",
            "base_url": "https://new",
            "model": "m2",
            "auth_required": False,
        },
    )

    assert updated.config["user_defined"] is True
    assert updated.config["base_url"] == "https://new"


def test_upsert_provider_config_cannot_promote_built_in_to_user_defined(tmp_path):
    repo = _repo(tmp_path)

    # Try to sneak user_defined into a built-in via config upsert
    updated = repo.upsert_provider_config(
        "openai-codex-oauth-llm",
        config={"user_defined": True, "provider": "codex-oauth"},
    )

    assert "user_defined" not in updated.config


def test_seed_provider_configs_migrates_codex_to_oauth_responses_api(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_provider_config(
        "openai-codex-oauth-llm",
        enabled=False,
        status="planned",
        config={
            "auth_type": "oauth",
            "provider": "openai-codex-oauth",
            "model": "codex-latest",
            "runner_supported": False,
        },
    )

    migrated = {
        provider.provider_id: provider
        for provider in repo.list_provider_configs()
    }["openai-codex-oauth-llm"]

    assert migrated.status == "available"
    assert migrated.config["config_version"] == 4
    assert migrated.config["provider"] == "codex-oauth"
    assert migrated.config["model"] == "gpt-5.4-mini"
    assert migrated.config["quick_model"] == "gpt-5.4-mini"
    assert migrated.config["deep_model"] == "gpt-5.4"
    assert migrated.config["developer_mode"] is True
    assert migrated.config["runner_supported"] is True
    assert migrated.config["graph_runner_supported"] is True
    assert migrated.config["role_models"]["coordinator"] == "gpt-5.4"
    assert migrated.config["role_models"]["agent"] == "gpt-5.4-mini"
    assert migrated.config["role_models"]["overrides"] == {}
    assert "oauth_authorization_url" not in migrated.config


def test_seed_provider_configs_clears_stale_codex_cli_fields(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_provider_config(
        "openai-codex-oauth-llm",
        enabled=False,
        status="available",
        config={
            "auth_required": False,
            "auth_type": "codex-cli-session",
            "provider": "codex-cli",
            "model": "codex-cli",
            "timeout": 120,
            "developer_mode": True,
            "experimental": True,
            "runner_supported": True,
            "graph_runner_supported": False,
            "oauth_authorization_url": "https://chatgpt.com/codex",
            "oauth_token_url": "",
            "config_version": 2,
        },
    )

    migrated = {
        provider.provider_id: provider
        for provider in repo.list_provider_configs()
    }["openai-codex-oauth-llm"]

    assert migrated.config["provider"] == "codex-oauth"
    assert migrated.config["graph_runner_supported"] is True
    assert "experimental" not in migrated.config
    assert "oauth_authorization_url" not in migrated.config
    assert "oauth_token_url" not in migrated.config


def test_latest_approval_status_controls_has_approval(tmp_path):
    repo = _repo(tmp_path)
    run = repo.create_run(RunConfig(ticker="AMD", trade_date="2026-04-30"))
    intent = repo.create_trade_intent(
        run_id=run.run_id,
        symbol="AMD",
        side="buy",
        notional=5000,
    )

    approval = repo.record_approval(
        intent_id=intent.intent_id,
        actor="mcurtis",
        action="approve_order",
        before_payload={"status": "previewed"},
        after_payload={"status": "approved"},
    )

    assert approval.intent_id == intent.intent_id
    assert repo.has_approval(intent.intent_id)

    repo.record_approval(
        intent_id=intent.intent_id,
        actor="mcurtis",
        action="approve_order",
        before_payload={"status": "approved"},
        after_payload={"status": "rejected"},
    )

    assert not repo.has_approval(intent.intent_id)


def test_later_rejection_action_clears_has_approval(tmp_path):
    repo = _repo(tmp_path)
    run = repo.create_run(RunConfig(ticker="AMD", trade_date="2026-04-30"))
    intent = repo.create_trade_intent(
        run_id=run.run_id,
        symbol="AMD",
        side="buy",
        notional=5000,
    )

    repo.record_approval(
        intent_id=intent.intent_id,
        actor="mcurtis",
        action="approve_order",
        before_payload={"status": "previewed"},
        after_payload={"status": "approved"},
    )
    repo.record_approval(
        intent_id=intent.intent_id,
        actor="mcurtis",
        action="reject_order",
        before_payload={"status": "approved"},
        after_payload={"status": "rejected"},
    )

    assert repo.has_approval(intent.intent_id) is False


def test_record_approval_ledger_decision_for_any_room_entity(tmp_path):
    repo = _repo(tmp_path)

    entry = repo.record_approval_ledger_entry(
        room_id="dashboard",
        source="briefing-room",
        entity_type="recommendation",
        entity_id="rec_nvda_opening",
        action="revise",
        actor="mcurtis",
        summary="Revise NVDA brief with tax impact before allocation.",
        payload={"symbol": "NVDA"},
    )
    entries = repo.list_approval_ledger_entries(room_id="dashboard")

    assert entry.room_id == "dashboard"
    assert entry.action == "revise"
    assert entries[0].entity_id == "rec_nvda_opening"
    assert entries[0].payload["symbol"] == "NVDA"


def test_create_trigger_records_event_driven_agent_wakeups(tmp_path):
    repo = _repo(tmp_path)

    trigger = repo.create_agent_trigger(
        name="Wake broker when NVDA sentiment flips negative",
        room_id="market",
        trigger_type="sentiment_flip",
        target_agent="broker-risk-agent",
        symbol="NVDA",
        condition={"sentiment": "negative", "source": "hourly-news-scan"},
        workflow_id="workflow_broker_watch",
        enabled=True,
    )
    triggers = repo.list_agent_triggers(symbol="nvda")

    assert trigger.symbol == "NVDA"
    assert trigger.trigger_type == "sentiment_flip"
    assert trigger.enabled is True
    assert triggers[0].target_agent == "broker-risk-agent"


def test_create_trade_thesis_records_research_handoff_without_order_authority(tmp_path):
    repo = _repo(tmp_path)

    thesis = repo.create_trade_thesis(
        symbol="nvda",
        source_report_id="run_nvda_overnight",
        source_room="research",
        target_room="market",
        direction="long",
        horizon="2-4 weeks",
        conviction=0.72,
        thesis="AI infrastructure demand supports a measured long thesis.",
        catalysts=["Blackwell supply update", "cloud capex revisions"],
        invalidation=["gross margin compression", "export control shock"],
        risk_notes="Advisory only. Broker agents must select and preview an algorithm separately.",
        payload={"suggested_algorithm": "trailing_stop"},
    )
    listed = repo.list_trade_theses(symbol="NVDA", status="proposed")

    assert thesis.symbol == "NVDA"
    assert thesis.status == "proposed"
    assert thesis.source_room == "research"
    assert thesis.target_room == "market"
    assert thesis.payload["suggested_algorithm"] == "trailing_stop"
    assert listed[0].thesis_id == thesis.thesis_id
    assert listed[0].catalysts == ["Blackwell supply update", "cloud capex revisions"]


def test_store_broker_order_updates_intent_status_with_plan_names(tmp_path):
    repo = _repo(tmp_path)
    run = repo.create_run(RunConfig(ticker="NVDA", trade_date="2026-04-30"))
    intent = repo.create_trade_intent(
        run_id=run.run_id,
        symbol="NVDA",
        side="buy",
        notional=10000,
    )

    order = repo.store_broker_order(
        intent_id=intent.intent_id,
        broker="alpaca",
        environment="paper",
        status="submitted",
        broker_order_id="broker-123",
    )
    reread = repo.get_trade_intent(intent.intent_id)

    assert intent.status == "previewed"
    assert order.intent_id == intent.intent_id
    assert order.broker_order_id == "broker-123"
    assert reread.status == "submitted"


def test_concurrent_first_provider_reads_do_not_duplicate_default_rows(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlmodel import Session
    from tradingagents.ui.db import create_session_factory, init_db
    from tradingagents.ui.models import ProviderConfigRecord
    from tradingagents.ui.repository import PROVIDERS
    engine, sessions = create_session_factory(f"sqlite:///{tmp_path/'concurrent-providers.db'}")
    init_db(engine)
    barrier = Barrier(2)
    original = Session.get
    def racing_get(self, model, key, *args, **kwargs):
        result = original(self, model, key, *args, **kwargs)
        if model is ProviderConfigRecord and key == PROVIDERS[0].id and result is None:
            barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(Session, "get", racing_get)
    def read():
        repo = UiRepository(sessions)
        return repo.list_provider_configs(), repo.list_provider_role_assignments()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: read(), range(2)))
    assert len(results[0][0]) == len(results[1][0]) == len(PROVIDERS)
    assert {r.role_key for r in results[0][1]} == {r.role_key for r in results[1][1]}
