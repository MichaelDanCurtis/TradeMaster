from datetime import date, datetime, timezone
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from tradingagents.ui.api import create_app as _create_app
from tradingagents.ui.brokers.fake import FakePaperBroker

def create_app(*args, **kwargs):
    # Legacy trade-flow tests explicitly opt into an isolated broker fixture.
    kwargs.setdefault("broker_providers", {"fixture-paper-broker": FakePaperBroker()})
    return _create_app(*args, **kwargs)

from tradingagents.ui.brokers.base import BrokerOrder
from tradingagents.ui.db import create_session_factory
from tradingagents.ui.events import RunConfig, RunEvent
from tradingagents.ui.market_data.base import MarketDataBar, MarketDataQuote
from tradingagents.ui.models import TradeIntentRecord
from tradingagents.ui.portfolio_data.base import (
    PortfolioAccount,
    PortfolioHolding,
    PortfolioTransaction,
)
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import RealRunResult


class FakeLangfuseObservation:
    trace_id = "0123456789abcdef0123456789abcdef"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def update(self, **kwargs) -> None:
        return None


class FakeLangfuseClient:
    def create_trace_id(self, seed: str) -> str:
        return "0123456789abcdef0123456789abcdef"

    def start_as_current_observation(self, **kwargs):
        return FakeLangfuseObservation()

    def get_trace_url(self, *, trace_id: str) -> str:
        return f"https://cloud.langfuse.com/project/local/traces/{trace_id}"

    def flush(self) -> None:
        return None


def test_health_endpoint_returns_ok(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "tradingagents-ui"}


def test_provider_registry_endpoint_returns_roles_and_capabilities(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.get("/api/providers")

    assert response.status_code == 200
    providers = response.json()["providers"]
    by_id = {provider["id"]: provider for provider in providers}

    assert by_id["simulated-market-data"]["status"] == "disabled"
    assert by_id["simulated-market-data"]["role"] == "market-data"
    assert "historical-bars" in by_id["alpaca-market-data"]["capabilities"]
    assert by_id["webull-market-data"]["status"] == "planned"
    assert "historical-bars" in by_id["webull-market-data"]["capabilities"]
    assert by_id["webull-broker"]["role"] == "brokerage"
    assert by_id["fake-paper-broker"]["role"] == "brokerage"
    assert by_id["plaid-investments"]["status"] == "needs_key"
    assert by_id["openai-llm"]["role"] == "llm"


def test_provider_config_endpoint_updates_secret_reference(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    updated = client.post(
        "/api/provider-configs/alpaca-market-data",
        json={
            "enabled": True,
            "secret_ref": "keychain:alpaca:paper",
            "config": {"feed": "iex", "raw_secret": "must-not-survive"},
        },
    )
    listed = client.get("/api/provider-configs")
    by_id = {provider["provider_id"]: provider for provider in listed.json()["providers"]}

    assert updated.status_code == 200
    assert updated.json()["secret_ref"] == "keychain:alpaca:paper"
    assert "raw_secret" not in updated.json()["config"]
    assert by_id["alpaca-market-data"]["enabled"] is True


def test_provider_role_assignment_endpoint_routes_agent_roles(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    defaults = client.get("/api/provider-role-assignments")
    updated = client.post(
        "/api/provider-role-assignments/research_llm",
        json={"provider_id": "lm-studio-llm"},
    )
    listed = client.get("/api/provider-role-assignments")
    by_role = {assignment["role_key"]: assignment for assignment in listed.json()["assignments"]}

    assert defaults.status_code == 200
    assert defaults.json()["assignments"][0]["provider_id"]
    assert updated.status_code == 200
    assert updated.json()["role_key"] == "research_llm"
    assert updated.json()["provider_id"] == "lm-studio-llm"
    assert by_role["research_llm"]["provider_id"] == "lm-studio-llm"
    assert by_role["broker"]["provider_id"] == "alpaca-paper-broker"


def test_runtime_status_reports_runner_provider_and_execution_policy(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post(
        "/api/provider-configs/lm-studio-llm",
        json={
            "enabled": True,
            "secret_ref": "env:LM_STUDIO_KEY",
            "config": {"base_url": "http://127.0.0.1:1234/v1", "model": "local-qwen"},
        },
    )
    client.post(
        "/api/provider-role-assignments/research_llm",
        json={"provider_id": "lm-studio-llm"},
    )

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    body = response.json()
    assert body["research_runner"]["mode"] == "llm-ui-runner"
    assert body["research_llm"]["provider_id"] == "lm-studio-llm"
    assert body["research_llm"]["secret_ref_configured"] is True
    assert body["research_llm"]["fallback_expected"] is False
    assert body["execution_policy"]["paper_mode_required"] is True
    assert body["execution_policy"]["max_position_percent"] == 10
    assert body["full_tradingagents_graph"]["enabled"] is False


def test_runtime_status_treats_local_lm_studio_as_runnable_without_secret(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post(
        "/api/provider-configs/lm-studio-llm",
        json={
            "enabled": True,
            "config": {
                "auth_required": False,
                "base_url": "http://127.0.0.1:1234/v1",
                "model": "local-qwen",
                "provider": "openai-compatible",
            },
        },
    )

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    body = response.json()
    assert body["research_llm"]["provider_id"] == "lm-studio-llm"
    assert body["research_llm"]["secret_ref_configured"] is False
    assert body["research_llm"]["fallback_expected"] is False


def test_runtime_status_allows_codex_developer_mode_for_safe_runner(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post("/api/runtime/developer-mode", json={"enabled": True})
    client.post(
        "/api/provider-configs/openai-codex-oauth-llm",
        json={"enabled": True, "secret_ref": None},
    )
    client.post(
        "/api/provider-role-assignments/research_llm",
        json={"provider_id": "openai-codex-oauth-llm"},
    )

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    body = response.json()
    assert body["research_llm"]["provider_id"] == "openai-codex-oauth-llm"
    assert body["research_llm"]["secret_ref_configured"] is False
    assert body["research_llm"]["developer_mode"] is True
    assert body["research_llm"]["fallback_expected"] is False


def test_runtime_status_accepts_codex_oauth_for_full_graph(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post("/api/runtime/developer-mode", json={"enabled": True})
    client.post(
        "/api/provider-configs/openai-codex-oauth-llm",
        json={"enabled": True, "secret_ref": None},
    )
    client.post(
        "/api/provider-role-assignments/research_llm",
        json={"provider_id": "openai-codex-oauth-llm"},
    )
    client.post(
        "/api/runtime/research-runner",
        json={"mode": "tradingagents-graph-runner"},
    )

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    body = response.json()
    assert body["research_llm"]["provider_id"] == "openai-codex-oauth-llm"
    assert body["research_llm"]["developer_mode"] is True
    assert body["research_llm"]["fallback_expected"] is False


def test_runtime_developer_mode_defaults_to_off_and_toggles(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    initial = client.get("/api/runtime/status").json()
    assert initial["developer_mode_enabled"] is False

    enabled = client.post("/api/runtime/developer-mode", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["developer_mode_enabled"] is True

    disabled = client.post("/api/runtime/developer-mode", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["developer_mode_enabled"] is False


def test_role_assignment_rejects_developer_provider_when_dev_mode_off(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    # Default developer_mode is off; assigning Codex (developer-tagged)
    # must be refused at the API boundary.
    response = client.post(
        "/api/provider-role-assignments/research_llm",
        json={"provider_id": "openai-codex-oauth-llm"},
    )
    assert response.status_code == 400
    assert "developer mode" in response.json()["detail"].lower()


def test_role_assignment_accepts_developer_provider_after_enabling_dev_mode(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post("/api/runtime/developer-mode", json={"enabled": True})

    response = client.post(
        "/api/provider-role-assignments/research_llm",
        json={"provider_id": "openai-codex-oauth-llm"},
    )
    assert response.status_code == 200
    assert response.json()["provider_id"] == "openai-codex-oauth-llm"


def test_role_assignment_unaffected_for_non_developer_providers(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    # Non-developer providers must still be assignable with dev mode off.
    response = client.post(
        "/api/provider-role-assignments/research_llm",
        json={"provider_id": "lm-studio-llm"},
    )
    assert response.status_code == 200


def test_create_user_provider_via_api_inserts_record(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.post(
        "/api/provider-configs",
        json={
            "name": "Z.AI GLM",
            "kind": "openai-compatible",
            "base_url": "https://api.z.ai/api/paas/v4/",
            "model": "glm-4.6",
            "api_key_env": "env:ZHIPU_API_KEY",
            "role_models": {
                "coordinator": "glm-4.6",
                "agent": "glm-4-air",
                "overrides": {},
            },
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["provider_id"] == "user:z-ai-glm"
    assert body["config"]["user_defined"] is True

    list_response = client.get("/api/provider-configs")
    ids = {p["provider_id"] for p in list_response.json()["providers"]}
    assert "user:z-ai-glm" in ids


def test_create_user_provider_via_api_rejects_invalid_kind(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.post(
        "/api/provider-configs",
        json={
            "name": "X",
            "kind": "grpc",  # unsupported
            "base_url": "https://x",
            "model": "m",
        },
    )
    assert response.status_code == 422  # pydantic Literal mismatch


def test_create_user_provider_via_api_rejects_duplicate_name(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    payload = {
        "name": "GLM",
        "kind": "openai-compatible",
        "base_url": "https://x",
        "model": "m",
    }
    assert client.post("/api/provider-configs", json=payload).status_code == 201
    response = client.post("/api/provider-configs", json={**payload, "base_url": "https://y"})
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_delete_user_provider_via_api_removes_record(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    create_response = client.post(
        "/api/provider-configs",
        json={
            "name": "Kimi",
            "kind": "openai-compatible",
            "base_url": "https://api.moonshot.ai/v1",
            "model": "moonshot-v1-128k",
        },
    )
    provider_id = create_response.json()["provider_id"]

    delete_response = client.delete(f"/api/provider-configs/{provider_id}")
    assert delete_response.status_code == 204

    list_response = client.get("/api/provider-configs")
    ids = {p["provider_id"] for p in list_response.json()["providers"]}
    assert provider_id not in ids


def test_delete_provider_via_api_refuses_built_in(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.delete("/api/provider-configs/openai-codex-oauth-llm")
    assert response.status_code == 400
    assert "user-defined" in response.json()["detail"]


def test_user_defined_provider_assignable_to_role(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    create_response = client.post(
        "/api/provider-configs",
        json={
            "name": "GLM",
            "kind": "openai-compatible",
            "base_url": "https://api.z.ai/api/paas/v4/",
            "model": "glm-4.6",
        },
    )
    provider_id = create_response.json()["provider_id"]

    # User-defined providers are not developer-tagged so dev mode toggle is irrelevant
    assign_response = client.post(
        f"/api/provider-role-assignments/research_llm",
        json={"provider_id": provider_id},
    )
    assert assign_response.status_code == 200

    # Deleting while assigned must fail with a clear error
    delete_response = client.delete(f"/api/provider-configs/{provider_id}")
    assert delete_response.status_code == 400
    assert "bound to roles" in delete_response.json()["detail"]


def test_runtime_status_reports_full_graph_runner_when_enabled(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADEMASTER_ENABLE_REAL_RUNS", "1")
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.get("/api/runtime/status")

    assert response.status_code == 200
    body = response.json()
    assert body["research_runner"]["mode"] == "tradingagents-graph-runner"
    assert body["full_tradingagents_graph"]["enabled"] is True
    assert body["full_tradingagents_graph"]["env_flag"] is True


def test_runtime_research_runner_endpoint_persists_full_graph_mode(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.post(
        "/api/runtime/research-runner",
        json={"mode": "tradingagents-graph-runner"},
    )
    status = client.get("/api/runtime/status")

    assert response.status_code == 200
    assert response.json()["research_runner"]["configured_mode"] == "tradingagents-graph-runner"
    assert response.json()["research_runner"]["mode"] == "tradingagents-graph-runner"
    assert response.json()["full_tradingagents_graph"]["enabled"] is True
    assert status.json()["research_runner"]["configured_mode"] == "tradingagents-graph-runner"
    assert status.json()["full_tradingagents_graph"]["configured"] is True


def test_runtime_research_runner_endpoint_rejects_unknown_mode(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.post("/api/runtime/research-runner", json={"mode": "fake-runner"})

    assert response.status_code == 422


def test_room_policy_endpoint_exposes_tool_grants_and_blocks_research_broker_tools(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    listed = client.get("/api/room-policies")
    decision = client.post(
        "/api/room-policies/evaluate",
        json={"room_id": "research", "tool_grant": "broker-paper-preview"},
    )

    assert listed.status_code == 200
    by_id = {room["room_id"]: room for room in listed.json()["rooms"]}
    assert by_id["research"]["label"] == "Research Office"
    assert "broker-paper-preview" not in by_id["research"]["tool_grants"]
    assert decision.status_code == 200
    assert decision.json()["allowed"] is False


def test_trade_preview_rejects_research_room_tool_use(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run = client.post(
        "/api/runs",
        json={
            "ticker": "NVDA",
            "trade_date": "2026-05-10",
            "broker_mode": "paper",
            "execution_mode": "real",
        },
    ).json()

    response = client.post(
        "/api/trades/preview",
        json={
            "run_id": run["run_id"],
            "symbol": "NVDA",
            "side": "buy",
            "notional": 1000,
            "room_id": "research",
        },
    )

    assert response.status_code == 403
    assert "Research Office does not grant broker-paper-preview" in response.json()["detail"]


def test_approval_ledger_and_trigger_endpoints_round_trip(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    ledger = client.post(
        "/api/approval-ledger",
        json={
            "room_id": "dashboard",
            "source": "briefing-room",
            "entity_type": "recommendation",
            "entity_id": "rec_nvda_opening",
            "action": "accept",
            "actor": "mcurtis",
            "summary": "Accept morning NVDA hold recommendation.",
            "payload": {"symbol": "NVDA"},
        },
    )
    trigger = client.post(
        "/api/agent-triggers",
        json={
            "name": "Hourly negative sentiment wakeup",
            "room_id": "market",
            "trigger_type": "sentiment_flip",
            "target_agent": "broker-risk-agent",
            "symbol": "NVDA",
            "condition": {"sentiment": "negative"},
            "workflow_id": "workflow_broker_watch",
            "enabled": True,
        },
    )
    ledger_list = client.get("/api/approval-ledger?room_id=dashboard")
    trigger_list = client.get("/api/agent-triggers?symbol=NVDA")

    assert ledger.status_code == 200
    assert trigger.status_code == 200
    assert ledger_list.json()["entries"][0]["action"] == "accept"
    assert trigger_list.json()["triggers"][0]["trigger_type"] == "sentiment_flip"


def test_enabled_report_schedule_creates_linked_perception_trigger(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    schedule = client.post(
        "/api/report-schedules",
        json={
            "name": "NVDA hourly sentiment perception",
            "symbol": "NVDA",
            "cadence": "hourly",
            "broker_mode": "disabled",
            "execution_mode": "real",
            "enabled": True,
            "payload": {"perception": "news_sentiment"},
        },
    )
    triggers = client.get("/api/agent-triggers?symbol=NVDA&enabled=true")

    assert schedule.status_code == 200
    assert triggers.status_code == 200
    trigger = triggers.json()["triggers"][0]
    assert trigger["trigger_type"] == "time"
    assert trigger["target_agent"] == "scheduled-perception-agent"
    assert trigger["workflow_id"] == schedule.json()["schedule_id"]
    assert trigger["condition"]["cadence"] == "hourly"
    assert trigger["payload"]["schedule_id"] == schedule.json()["schedule_id"]


def test_trade_thesis_endpoints_round_trip_advisory_handoff(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/trade-theses",
        json={
            "symbol": "nvda",
            "source_report_id": "run_nvda_overnight",
            "source_room": "research",
            "target_room": "market",
            "direction": "long",
            "horizon": "2-4 weeks",
            "conviction": 0.72,
            "thesis": "AI infrastructure demand supports a measured long thesis.",
            "catalysts": ["Blackwell supply update", "cloud capex revisions"],
            "invalidation": ["gross margin compression", "export control shock"],
            "risk_notes": "Advisory only; broker agents must preview execution separately.",
            "payload": {"suggested_algorithm": "trailing_stop"},
        },
    )
    listed = client.get("/api/trade-theses?symbol=NVDA&status=proposed")

    assert created.status_code == 200
    assert created.json()["symbol"] == "NVDA"
    assert created.json()["status"] == "proposed"
    assert listed.status_code == 200
    assert listed.json()["theses"][0]["source_room"] == "research"
    assert listed.json()["theses"][0]["target_room"] == "market"


def test_provider_secret_health_check_reports_availability_and_audits(
    tmp_path: Path,
    monkeypatch,
):
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(database_url))
    _, session_factory = create_session_factory(database_url)
    repo = UiRepository(session_factory)
    monkeypatch.setenv("TRADEMASTER_ALPACA_CREDS", "not-returned")
    client.post(
        "/api/provider-configs/alpaca-market-data",
        json={
            "enabled": True,
            "secret_ref": "env:TRADEMASTER_ALPACA_CREDS",
        },
    )

    response = client.post("/api/provider-configs/alpaca-market-data/health-check")
    events = repo.list_private_office_events()

    assert response.status_code == 200
    assert response.json()["health"]["secret"] == {
        "backend": "env",
        "available": True,
    }
    assert "not-returned" not in str(response.json())
    assert events[-1].event_type == "provider.health_checked"
    assert events[-1].actor == "Provider Registry"
    assert events[-1].entity_id == "provider_alpaca_market_data"
    assert events[-1].payload["secret_available"] is True


def test_provider_secret_health_check_reports_missing_secret(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post(
        "/api/provider-configs/alpaca-market-data",
        json={
            "enabled": True,
            "secret_ref": "env:MISSING_TRADEMASTER_ALPACA_CREDS",
        },
    )

    response = client.post("/api/provider-configs/alpaca-market-data/health-check")

    assert response.status_code == 200
    assert response.json()["status"] == "needs_key"
    assert response.json()["health"]["secret"] == {
        "backend": "env",
        "available": False,
    }


def test_private_office_event_endpoint_appends_ledger_event(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.post(
        "/api/private-office/events",
        json={
            "event_type": "agent.message.created",
            "summary": "Goals team updated the yacht dossier.",
            "actor": "Goal Steward",
            "entity_id": "goal_yacht",
            "payload": {"surface": "goal-dossier"},
        },
    )

    assert response.status_code == 200
    assert response.json()["event_type"] == "agent.message.created"
    assert response.json()["payload"] == {"surface": "goal-dossier"}


def test_goal_endpoints_create_and_list_durable_goal_dossiers(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/goals",
        json={
            "goal_id": "goal_yacht",
            "label": "Absolute Navetta 68",
            "target_amount": 4750000,
            "target_date": "2026-11-01",
            "status": "planning",
            "payload": {"location": "Hawaii", "advisor_notes": ["Review ownership structure"]},
        },
    )
    listed = client.get("/api/goals")

    assert created.status_code == 200
    assert created.json()["entity_id"] == "goal_yacht"
    assert created.json()["entity_type"] == "goal"
    assert created.json()["payload"]["target_amount"] == 4750000
    assert listed.status_code == 200
    assert listed.json()["goals"][0]["label"] == "Absolute Navetta 68"


def test_asset_endpoints_create_and_list_durable_asset_dossiers(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/assets",
        json={
            "asset_id": "asset_navetta_68",
            "label": "Absolute Navetta 68",
            "asset_type": "boat",
            "jurisdiction": "Hawaii",
            "status": "target",
            "payload": {"liability_notes": ["Moorage and insurance review required"]},
        },
    )
    listed = client.get("/api/assets")

    assert created.status_code == 200
    assert created.json()["entity_id"] == "asset_navetta_68"
    assert created.json()["entity_type"] == "asset"
    assert created.json()["payload"]["asset_type"] == "boat"
    assert listed.status_code == 200
    assert listed.json()["assets"][0]["payload"]["jurisdiction"] == "Hawaii"


def test_private_office_edge_endpoint_links_goal_to_asset(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post(
        "/api/goals",
        json={"goal_id": "goal_yacht", "label": "Absolute Navetta 68"},
    )
    client.post(
        "/api/assets",
        json={
            "asset_id": "asset_navetta_68",
            "label": "Absolute Navetta 68",
            "asset_type": "boat",
        },
    )

    created = client.post(
        "/api/private-office/edges",
        json={
            "source_entity_id": "goal_yacht",
            "target_entity_id": "asset_navetta_68",
            "relationship": "targets_asset",
            "payload": {"confidence": "candidate"},
        },
    )
    listed = client.get(
        "/api/private-office/edges",
        params={"source_entity_id": "goal_yacht"},
    )

    assert created.status_code == 200
    assert created.json()["relationship"] == "targets_asset"
    assert listed.status_code == 200
    assert listed.json()["edges"][0]["target_entity_id"] == "asset_navetta_68"


def test_portfolio_mandate_endpoints_create_and_filter_mandates(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    human = client.post(
        "/api/portfolio-mandates",
        json={
            "name": "Webull assisted strategy",
            "control_mode": "human-managed-assisted",
            "account_ref": "webull:human",
            "funding_limit": 250000,
            "max_position_percent": 20,
            "max_drawdown_percent": 12,
            "daily_turnover_limit_percent": 15,
            "paper_mode_required": False,
            "kill_switch_enabled": True,
            "status": "active",
        },
    )
    high_risk = client.post(
        "/api/portfolio-mandates",
        json={
            "name": "AI high-risk paper harness",
            "control_mode": "ai-managed-high-risk",
            "account_ref": "alpaca:paper:high-risk",
            "funding_limit": 50000,
            "max_position_percent": 10,
            "max_drawdown_percent": 8,
            "daily_turnover_limit_percent": 20,
            "paper_mode_required": True,
            "kill_switch_enabled": True,
            "status": "draft",
            "payload": {"proving_phase": "paper"},
        },
    )
    filtered = client.get(
        "/api/portfolio-mandates",
        params={"control_mode": "ai-managed-high-risk"},
    )

    assert human.status_code == 200
    assert human.json()["control_mode"] == "human-managed-assisted"
    assert high_risk.status_code == 200
    assert high_risk.json()["paper_mode_required"] is True
    assert filtered.status_code == 200
    assert [item["name"] for item in filtered.json()["mandates"]] == [
        "AI high-risk paper harness"
    ]


def test_portfolio_mandate_endpoint_rejects_high_risk_without_kill_switch(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.post(
        "/api/portfolio-mandates",
        json={
            "name": "AI high-risk unsafe",
            "control_mode": "ai-managed-high-risk",
            "account_ref": "alpaca:paper:high-risk",
            "funding_limit": 50000,
            "max_position_percent": 10,
            "max_drawdown_percent": 8,
            "daily_turnover_limit_percent": 20,
            "paper_mode_required": True,
            "kill_switch_enabled": False,
        },
    )

    assert response.status_code == 400
    assert "kill switch" in response.json()["detail"]


def test_agent_workflow_endpoints_persist_graph_manifest_and_provider_roles(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/agent-workflows",
        json={
            "name": "NVDA research with execution guard",
            "agent_class": "research",
            "graph_runtime": "langgraph",
            "status": "draft",
            "nodes": [
                {"id": "market-analyst", "kind": "agent"},
                {"id": "research-manager", "kind": "agent"},
                {"id": "pyreason-circuit-breaker", "kind": "control"},
            ],
            "edges": [
                {"source": "market-analyst", "target": "research-manager"},
                {"source": "research-manager", "target": "pyreason-circuit-breaker"},
            ],
            "required_provider_roles": {
                "research_llm": "openai-llm",
                "execution_llm": "mistral-medium-execution-llm",
                "market_data": "alpaca-market-data",
                "broker": "alpaca-paper-broker",
                "safety": "pyreason-circuit-breaker",
            },
            "payload": {"symbol": "NVDA"},
        },
    )
    listed = client.get("/api/agent-workflows")

    assert created.status_code == 200
    assert created.json()["name"] == "NVDA research with execution guard"
    assert created.json()["graph_runtime"] == "langgraph"
    assert created.json()["required_provider_roles"]["research_llm"] == "openai-llm"
    assert listed.status_code == 200
    assert listed.json()["workflows"][0]["nodes"][0]["id"] == "market-analyst"


def test_snapshot_endpoint_creates_manifest_for_local_sqlite(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(database_url))

    response = client.post(
        "/api/snapshots",
        json={"encryption_mode": "age", "offsite_target": "backblaze-b2"},
    )

    assert response.status_code == 200
    assert response.json()["storage_profile"] == "sqlite-local"
    assert response.json()["encryption_mode"] == "none"
    assert response.json()["manifest"]["encrypted"] is False
    assert response.json()["manifest"]["files"][0]["path"] == str(tmp_path / "ui.db")
    assert len(response.json()["manifest"]["files"][0]["sha256"]) == 64


def test_snapshot_endpoint_creates_encrypted_bundle_from_secret_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("TRADEMASTER_BACKUP_KEY", "local backup key")
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(database_url))

    response = client.post(
        "/api/snapshots",
        json={
            "backup_key_ref": "env:TRADEMASTER_BACKUP_KEY",
            "offsite_target": "manual-offsite",
        },
    )

    assert response.status_code == 200
    body = response.json()
    artifact = body["manifest"]["backup_artifact"]
    artifact_path = Path(artifact["path"])
    assert body["encryption_mode"] == "local-aes-256-gcm"
    assert artifact["algorithm"] == "AES-256-GCM"
    assert artifact_path.exists()
    assert b"sqlite_master" not in artifact_path.read_bytes()
    assert "local backup key" not in str(body)


def test_snapshot_verify_endpoint_checks_encrypted_bundle_from_secret_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("TRADEMASTER_BACKUP_KEY", "local backup key")
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(database_url))
    created = client.post(
        "/api/snapshots",
        json={"backup_key_ref": "env:TRADEMASTER_BACKUP_KEY"},
    ).json()

    verification = client.post(
        f"/api/snapshots/{created['snapshot_id']}/verify",
        json={"backup_key_ref": "env:TRADEMASTER_BACKUP_KEY"},
    )

    assert verification.status_code == 200
    assert verification.json()["valid"] is True
    assert verification.json()["manifest"]["snapshot_id"] == created["snapshot_id"]
    assert verification.json()["files"][0]["verified"] is True


def test_market_data_bars_endpoint_returns_normalized_provider_data(tmp_path: Path):
    class FakeMarketDataProvider:
        def historical_bars(self, **kwargs):
            return [
                MarketDataBar(
                    symbol=kwargs["symbol"].upper(),
                    timestamp=datetime(2026, 4, 30, 13, 30, tzinfo=timezone.utc),
                    open=838.12,
                    high=841.0,
                    low=836.5,
                    close=839.05,
                    volume=6601542,
                    vwap=838.71,
                    trade_count=9342,
                )
            ]

        def latest_quote(self, symbol: str, *, feed: str | None = None):
            raise AssertionError("not used")

    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            market_data_providers={"alpaca-market-data": FakeMarketDataProvider()},
        )
    )

    response = client.get(
        "/api/market-data/alpaca-market-data/bars",
        params={
            "symbol": "nvda",
            "start": "2026-04-30T13:30:00Z",
            "end": "2026-04-30T20:00:00Z",
            "timeframe": "1Min",
            "limit": "100",
            "feed": "iex",
        },
    )

    assert response.status_code == 200
    assert response.json()["bars"][0]["symbol"] == "NVDA"
    assert response.json()["bars"][0]["timestamp"] == "2026-04-30T13:30:00Z"
    assert response.json()["bars"][0]["vwap"] == 838.71


def test_market_data_bars_endpoint_records_sqlite_snapshot(tmp_path: Path):
    class FakeMarketDataProvider:
        def historical_bars(self, **kwargs):
            return [
                MarketDataBar(
                    symbol=kwargs["symbol"].upper(),
                    timestamp=datetime(2026, 4, 30, 13, 30, tzinfo=timezone.utc),
                    open=838.12,
                    high=841.0,
                    low=836.5,
                    close=839.05,
                    volume=6601542,
                    vwap=838.71,
                    trade_count=9342,
                )
            ]

        def latest_quote(self, symbol: str, *, feed: str | None = None):
            raise AssertionError("not used")

    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(
        create_app(
            database_url,
            market_data_providers={"alpaca-market-data": FakeMarketDataProvider()},
        )
    )

    response = client.get(
        "/api/market-data/alpaca-market-data/bars",
        params={
            "symbol": "nvda",
            "start": "2026-04-30T13:30:00Z",
            "end": "2026-04-30T20:00:00Z",
            "timeframe": "1Min",
            "feed": "iex",
        },
    )

    assert response.status_code == 200
    _, session_factory = create_session_factory(database_url)
    snapshots = UiRepository(session_factory).list_market_data_snapshots(symbol="NVDA")
    assert len(snapshots) == 1
    assert snapshots[0].provider_id == "alpaca-market-data"
    assert snapshots[0].snapshot_kind == "bars"
    assert snapshots[0].feed == "iex"
    assert snapshots[0].payload["bars"][0]["close"] == 839.05


def test_market_data_quote_endpoint_returns_normalized_provider_data(tmp_path: Path):
    class FakeMarketDataProvider:
        def historical_bars(self, **kwargs):
            raise AssertionError("not used")

        def latest_quote(self, symbol: str, *, feed: str | None = None):
            return MarketDataQuote(
                symbol=symbol.upper(),
                timestamp=datetime(2026, 4, 30, 13, 30, 1, tzinfo=timezone.utc),
                bid_price=838.95,
                bid_size=200,
                ask_price=839.1,
                ask_size=300,
            )

    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            market_data_providers={"alpaca-market-data": FakeMarketDataProvider()},
        )
    )

    response = client.get(
        "/api/market-data/alpaca-market-data/quote",
        params={"symbol": "nvda", "feed": "iex"},
    )

    assert response.status_code == 200
    assert response.json()["quote"]["symbol"] == "NVDA"
    assert response.json()["quote"]["timestamp"] == "2026-04-30T13:30:01Z"
    assert response.json()["quote"]["ask_size"] == 300


def test_market_data_endpoint_builds_alpaca_provider_from_provider_config(
    tmp_path: Path,
    monkeypatch,
):
    class FakeResponse:
        def json(self):
            return {
                "bars": [
                    {
                        "t": "2026-04-30T13:30:00Z",
                        "o": 838.12,
                        "h": 841.0,
                        "l": 836.5,
                        "c": 839.05,
                        "v": 6601542,
                        "vw": 838.71,
                        "n": 9342,
                    }
                ]
            }

        def raise_for_status(self):
            return None

    class RecordingHttpClient:
        def __init__(self) -> None:
            self.calls = []

        def get(self, url: str, *, headers: dict, params: dict, timeout: float):
            self.calls.append(
                {
                    "url": url,
                    "headers": headers,
                    "params": params,
                    "timeout": timeout,
                }
            )
            return FakeResponse()

    monkeypatch.setenv(
        "TRADEMASTER_ALPACA_CREDS",
        '{"key_id":"paper-key","secret_key":"paper-secret"}',
    )
    http_client = RecordingHttpClient()
    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            market_data_http_client=http_client,
        )
    )
    client.post(
        "/api/provider-configs/alpaca-market-data",
        json={
            "enabled": True,
            "secret_ref": "env:TRADEMASTER_ALPACA_CREDS",
            "config": {"feed": "iex"},
        },
    )

    response = client.get(
        "/api/market-data/alpaca-market-data/bars",
        params={
            "symbol": "NVDA",
            "start": "2026-04-30T13:30:00Z",
            "end": "2026-04-30T20:00:00Z",
            "timeframe": "1Min",
        },
    )

    assert response.status_code == 200
    assert http_client.calls[0]["headers"] == {
        "APCA-API-KEY-ID": "paper-key",
        "APCA-API-SECRET-KEY": "paper-secret",
    }
    assert http_client.calls[0]["params"]["feed"] == "iex"


def test_market_data_endpoint_returns_controlled_error_when_secret_missing(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post(
        "/api/provider-configs/alpaca-market-data",
        json={
            "enabled": True,
            "secret_ref": "env:MISSING_TRADEMASTER_ALPACA_CREDS",
        },
    )

    response = client.get(
        "/api/market-data/alpaca-market-data/quote",
        params={"symbol": "NVDA"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Market data secret is not available"}


def test_portfolio_data_endpoints_return_read_only_plaid_context(tmp_path: Path):
    class FakePortfolioProvider:
        def accounts(self):
            return [
                PortfolioAccount(
                    account_id="acc_1",
                    name="Brokerage",
                    type="investment",
                    subtype="brokerage",
                    current_balance=125000.25,
                    iso_currency_code="USD",
                )
            ]

        def holdings(self):
            return [
                PortfolioHolding(
                    account_id="acc_1",
                    security_id="sec_nvda",
                    symbol="NVDA",
                    name="NVIDIA Corporation",
                    quantity=12.5,
                    price=839.05,
                    value=10488.125,
                    cost_basis=8000.0,
                )
            ]

        def transactions(self, *, start_date: date, end_date: date):
            return [
                PortfolioTransaction(
                    transaction_id="txn_1",
                    account_id="acc_1",
                    date=start_date,
                    name="Deposit",
                    amount=-5000,
                    iso_currency_code="USD",
                    categories=["Transfer", "Deposit"],
                )
            ]

    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            portfolio_providers={"plaid-investments": FakePortfolioProvider()},
        )
    )

    accounts = client.get("/api/portfolio-data/plaid-investments/accounts")
    holdings = client.get("/api/portfolio-data/plaid-investments/holdings")
    transactions = client.get(
        "/api/portfolio-data/plaid-investments/transactions",
        params={"start_date": "2026-04-01", "end_date": "2026-04-30"},
    )

    assert accounts.status_code == 200
    assert accounts.json()["accounts"][0]["current_balance"] == 125000.25
    assert holdings.status_code == 200
    assert holdings.json()["holdings"][0]["symbol"] == "NVDA"
    assert transactions.status_code == 200
    assert transactions.json()["transactions"][0]["categories"] == ["Transfer", "Deposit"]


def test_portfolio_data_endpoint_builds_plaid_provider_from_provider_config(
    tmp_path: Path,
    monkeypatch,
):
    class FakeResponse:
        def json(self):
            return {
                "accounts": [
                    {
                        "account_id": "acc_1",
                        "name": "Brokerage",
                        "type": "investment",
                        "balances": {
                            "current": 125000.25,
                            "iso_currency_code": "USD",
                        },
                    }
                ]
            }

        def raise_for_status(self):
            return None

    class RecordingHttpClient:
        def __init__(self) -> None:
            self.calls = []

        def post(self, url: str, *, json: dict, timeout: float):
            self.calls.append({"url": url, "json": json, "timeout": timeout})
            return FakeResponse()

    monkeypatch.setenv(
        "TRADEMASTER_PLAID_CREDS",
        '{"client_id":"client","secret":"sandbox-secret","access_token":"access-sandbox"}',
    )
    http_client = RecordingHttpClient()
    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            portfolio_http_client=http_client,
        )
    )
    client.post(
        "/api/provider-configs/plaid-investments",
        json={
            "enabled": True,
            "secret_ref": "env:TRADEMASTER_PLAID_CREDS",
        },
    )

    response = client.get("/api/portfolio-data/plaid-investments/accounts")

    assert response.status_code == 200
    assert response.json()["accounts"][0]["account_id"] == "acc_1"
    assert "sandbox-secret" not in str(response.json())
    assert http_client.calls[0]["url"] == "https://production.plaid.com/accounts/balance/get"
    assert http_client.calls[0]["json"] == {
        "client_id": "client",
        "secret": "sandbox-secret",
        "access_token": "access-sandbox",
    }


def test_create_run_and_fetch_events(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "disabled", "execution_mode": "simulated"},
    )
    run_id = created.json()["run_id"]
    events = client.get(f"/api/runs/{run_id}/events")

    assert created.status_code == 200
    assert created.json()["status"] == "completed"
    assert events.status_code == 200
    assert events.json()[0]["type"] == "run.created"


def test_create_real_run_returns_running_without_waiting_for_runner(tmp_path: Path):
    class SlowRealRunner:
        def __call__(self, run_id: str, config: RunConfig) -> RealRunResult:
            time.sleep(0.25)
            return RealRunResult(
                events=[],
                rating="Neutral",
                action="Hold",
                thesis="Slow real graph completed.",
            )

    client = TestClient(
        create_app(f"sqlite:///{tmp_path / 'ui.db'}", real_runner=SlowRealRunner())
    )

    started = time.monotonic()
    created = client.post(
        "/api/runs",
        json={
            "ticker": "NVDA",
            "trade_date": "2026-04-30",
            "broker_mode": "disabled",
            "execution_mode": "real",
        },
    )
    elapsed = time.monotonic() - started

    assert created.status_code == 200
    assert created.json()["status"] == "running"
    assert elapsed < 0.2


def test_list_runs_can_filter_by_ticker(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "disabled", "execution_mode": "simulated"},
    )
    client.post(
        "/api/runs",
        json={"ticker": "AAPL", "trade_date": "2026-04-30", "broker_mode": "disabled", "execution_mode": "simulated"},
    )

    response = client.get("/api/runs?ticker=nvda&limit=1")

    assert response.status_code == 200
    assert len(response.json()["runs"]) == 1
    assert response.json()["runs"][0]["ticker"] == "NVDA"
    assert response.json()["runs"][0]["final_rating"] == "Overweight"


def test_create_list_and_trigger_report_schedule(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/report-schedules",
        json={
            "name": "NVDA opening stance",
            "symbol": "NVDA",
            "cadence": "market_open",
            "broker_mode": "disabled",
            "execution_mode": "real",
            "enabled": True,
        },
    )
    schedule_id = created.json()["schedule_id"]
    triggered = client.post(f"/api/report-schedules/{schedule_id}/trigger")
    schedules = client.get("/api/report-schedules?symbol=nvda")

    assert created.status_code == 200
    assert created.json()["symbol"] == "NVDA"
    assert triggered.status_code == 200
    assert triggered.json()["schedule"]["last_run_id"] == triggered.json()["run"]["run_id"]
    assert triggered.json()["run"]["status"] == "completed"
    assert schedules.status_code == 200
    assert schedules.json()["schedules"][0]["last_run_id"] == triggered.json()["run"]["run_id"]


def test_trigger_enabled_report_schedules_skips_disabled(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post(
        "/api/report-schedules",
        json={
            "name": "NVDA opening stance",
            "symbol": "NVDA",
            "cadence": "market_open",
            "enabled": True,
        },
    )
    client.post(
        "/api/report-schedules",
        json={
            "name": "AAPL opening stance",
            "symbol": "AAPL",
            "cadence": "market_open",
            "enabled": False,
        },
    )

    response = client.post("/api/report-schedules/trigger-enabled")

    assert response.status_code == 200
    assert response.json()["triggered_count"] == 1
    assert response.json()["results"][0]["schedule"]["symbol"] == "NVDA"
    assert response.json()["results"][0]["run"]["status"] == "completed"


def test_list_execution_algorithm_catalogue(tmp_path: Path):
    """The catalogue endpoint exposes every registered algorithm grouped by category."""

    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.get("/api/execution-algorithms")
    assert response.status_code == 200
    body = response.json()

    assert body["total"] >= 20  # overnight brief required at least 20
    assert {cat["id"] for cat in body["categories"]} == {
        "time_based",
        "momentum",
        "mean_reversion",
        "volatility",
        "microstructure",
        "event_driven",
    }
    # Every category carries algorithms; legacy names still present in microstructure.
    micro = next(c for c in body["categories"] if c["id"] == "microstructure")
    micro_names = {a["name"] for a in micro["algorithms"]}
    assert {"bracket_order", "trailing_stop", "dca_ladder"} <= micro_names
    # Every algorithm has a non-empty description.
    for cat in body["categories"]:
        for algo in cat["algorithms"]:
            assert algo["description"]


def test_preview_execution_algorithm(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.post(
        "/api/execution-algorithms/preview",
        json={
            "algorithm": "bracket_order",
            "symbol": "NVDA",
            "side": "buy",
            "notional": 1000,
            "reference_price": 200,
        },
    )

    assert response.status_code == 200
    assert response.json()["algorithm"] == "bracket_order"
    assert [leg["kind"] for leg in response.json()["legs"]] == [
        "market_entry",
        "take_profit",
        "stop_loss",
    ]


def test_fetch_run_observability_trace(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={
            "ticker": "NVDA",
            "trade_date": "2026-04-30",
            "execution_mode": "simulated",
        },
    ).json()["run_id"]

    response = client.get(f"/api/runs/{run_id}/trace")

    assert response.status_code == 200
    assert response.json()["run_id"] == run_id
    assert response.json()["status"] == "completed"
    assert response.json()["metadata"]["ticker"] == "NVDA"
    assert response.json()["metadata"]["execution_mode"] == "simulated"


def test_export_run_observability_trace_to_langfuse(tmp_path: Path, monkeypatch):
    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            langfuse_client_factory=lambda credentials: FakeLangfuseClient(),
        )
    )
    monkeypatch.setenv(
        "TRADEMASTER_LANGFUSE_CREDS",
        '{"public_key":"pk-lf-local","secret_key":"sk-lf-local","base_url":"https://cloud.langfuse.com"}',
    )
    client.post(
        "/api/provider-configs/langfuse-observability",
        json={
            "enabled": True,
            "secret_ref": "env:TRADEMASTER_LANGFUSE_CREDS",
        },
    )
    run_id = client.post(
        "/api/runs",
        json={
            "ticker": "NVDA",
            "trade_date": "2026-04-30",
            "execution_mode": "simulated",
        },
    ).json()["run_id"]

    response = client.post(f"/api/runs/{run_id}/trace/export")

    assert response.status_code == 200
    assert response.json()["provider"] == "langfuse-observability"
    assert response.json()["status"] == "exported"
    assert response.json()["external_trace_id"] == "0123456789abcdef0123456789abcdef"
    assert response.json()["metadata"]["exported_to"] == "langfuse"
    assert "sk-lf-local" not in str(response.json())


def test_export_run_observability_trace_requires_configured_langfuse_provider(
    tmp_path: Path,
):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={
            "ticker": "NVDA",
            "trade_date": "2026-04-30",
            "execution_mode": "simulated",
        },
    ).json()["run_id"]

    response = client.post(f"/api/runs/{run_id}/trace/export")

    assert response.status_code == 403
    assert response.json() == {
        "detail": "LangFuse observability is disabled or missing a secret_ref"
    }


def test_create_real_run_uses_injected_real_runner(tmp_path: Path):
    class FakeRealRunner:
        def __call__(self, run_id: str, config: RunConfig) -> RealRunResult:
            return RealRunResult(
                events=[
                    RunEvent(
                        run_id=run_id,
                        sequence=1,
                        type="decision.created",
                        node="Portfolio Manager",
                        message=f"Created real decision for {config.ticker}.",
                        payload={"rating": "Neutral", "action": "Hold"},
                    )
                ],
                rating="Neutral",
                action="Hold",
                thesis="Injected real runner result.",
            )

    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            real_runner=FakeRealRunner(),
        )
    )

    created = client.post(
        "/api/runs",
        json={
            "ticker": "NVDA",
            "trade_date": "2026-04-30",
            "execution_mode": "real",
        },
    )
    run_id = created.json()["run_id"]
    events = _wait_for_terminal_events(client, run_id)

    assert created.status_code == 200
    assert created.json()["status"] == "running"
    assert [event["type"] for event in events[:2]] == ["run.created", "run.started"]
    assert "decision.created" in [event["type"] for event in events]
    assert events[-1]["type"] == "run.completed"


def test_create_real_run_uses_configured_llm_provider(tmp_path: Path, monkeypatch):
    class FakeLlm:
        def invoke(self, prompt: str):
            assert "Ticker: NVDA" in prompt
            return type(
                "FakeResponse",
                (),
                {
                    "content": (
                        '{"rating":"Overweight","action":"Buy","thesis":"LLM sees a constructive setup.",'
                        '"risk_notes":"Position sizing and approval gate required.","confidence":0.72}'
                    )
                },
            )()

    class FakeLlmClient:
        def __init__(self) -> None:
            self.llm = FakeLlm()

        def get_llm(self):
            return self.llm

    calls: list[dict[str, object]] = []

    def fake_llm_client_factory(provider: str, model: str, **kwargs):
        calls.append({"provider": provider, "model": model, **kwargs})
        return FakeLlmClient()

    monkeypatch.setenv("TRADEMASTER_OPENAI_KEY", "sk-test-not-returned")
    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            llm_client_factory=fake_llm_client_factory,
        )
    )
    client.post(
        "/api/provider-configs/openai-llm",
        json={
            "enabled": True,
            "secret_ref": "env:TRADEMASTER_OPENAI_KEY",
            "config": {"model": "gpt-5.4-mini"},
        },
    )
    client.post(
        "/api/provider-role-assignments/research_llm",
        json={"provider_id": "openai-llm"},
    )

    created = client.post(
        "/api/runs",
        json={
            "ticker": "NVDA",
            "trade_date": "2026-04-30",
            "execution_mode": "real",
            "broker_mode": "disabled",
        },
    )
    run_id = created.json()["run_id"]
    events = _wait_for_terminal_events(client, run_id)
    trace = client.get(f"/api/runs/{run_id}/trace").json()

    assert created.status_code == 200
    assert created.json()["status"] == "running"
    assert calls[0]["provider"] == "openai"
    assert calls[0]["model"] == "gpt-5.4-mini"
    assert calls[0]["api_key"] == "sk-test-not-returned"
    decision = next(event for event in events if event["type"] == "decision.created")
    assert decision["payload"]["rating"] == "Overweight"
    assert decision["payload"]["action"] == "Buy"
    assert decision["payload"]["fallback"] is False
    assert trace["metadata"]["final_action"] == "Buy"
    assert "sk-test-not-returned" not in str(events)
    assert "sk-test-not-returned" not in str(trace)


def test_create_real_run_falls_back_when_llm_provider_is_not_configured(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post("/api/provider-configs/lm-studio-llm", json={"enabled": False})

    created = client.post(
        "/api/runs",
        json={
            "ticker": "NVDA",
            "trade_date": "2026-04-30",
            "execution_mode": "real",
            "broker_mode": "disabled",
        },
    )
    run_id = created.json()["run_id"]
    events = _wait_for_terminal_events(client, run_id)

    assert created.status_code == 200
    assert created.json()["status"] == "running"
    decision = next(event for event in events if event["type"] == "decision.created")
    assert decision["payload"]["fallback"] is True
    assert decision["payload"]["action"] == "Hold"
    assert "provider_not_configured" in str(events)


def _wait_for_terminal_events(client: TestClient, run_id: str) -> list[dict[str, object]]:
    deadline = time.monotonic() + 2
    latest: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        latest = client.get(f"/api/runs/{run_id}/events").json()
        if any(event["type"] in {"run.completed", "run.failed"} for event in latest):
            return latest
        time.sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach a terminal event: {latest}")


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


def test_missing_run_events_return_404(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.get("/api/runs/missing/events")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}


def test_missing_run_stream_returns_404(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.get("/api/runs/missing/stream")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}


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
    approval = client.post(
        f"/api/trades/{intent_id}/approve", json={"actor": "local-user"}
    )
    submitted = client.post(f"/api/trades/{intent_id}/submit")

    assert preview.status_code == 200
    assert preview.json()["environment"] == "paper"
    assert blocked_submit.status_code == 403
    assert approval.status_code == 200
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "accepted"


def test_trade_ticket_uses_configured_alpaca_paper_broker_after_approval(tmp_path: Path):
    from tradingagents.ui.brokers.fake import FakePaperBroker

    class RecordingAlpacaPaperBroker(FakePaperBroker):
        broker_name = "alpaca"

        def __init__(self):
            super().__init__()
            self.submitted = []

        def estimate_price(self, symbol: str) -> float:
            return 199.5

        def submit_exact_order(self, client_order_id, order):
            self.submitted.append({"intent_id": client_order_id, "quantity": order.quantity,
                "limit_price": str(order.limit_price_usd), "side": order.side, "symbol": order.symbol})
            return super().submit_exact_order(client_order_id, order)

    broker = RecordingAlpacaPaperBroker()
    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            broker_providers={"alpaca-paper-broker": broker},
        )
    )
    client.post(
        "/api/provider-configs/alpaca-paper-broker",
        json={
            "enabled": True,
            "secret_ref": "keychain:trademaster-alpaca:paper",
            "status": "available",
        },
    )
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
    approval = client.post(
        f"/api/trades/{intent_id}/approve", json={"actor": "local-user"}
    )
    submitted = client.post(f"/api/trades/{intent_id}/submit")

    assert preview.status_code == 200
    assert preview.json()["broker"] == "alpaca"
    assert preview.json()["estimated_price"] == 199.5
    assert blocked_submit.status_code == 403
    assert approval.status_code == 200
    assert submitted.status_code == 200
    assert submitted.json()["broker"] == "alpaca"
    assert submitted.json()["status"] == "accepted"
    assert broker.submitted == [
        {
            "intent_id": intent_id,
            "quantity": 5,
            "limit_price": "199.50",
            "side": "buy",
            "symbol": "NVDA",
        }
    ]


def test_disabled_run_rejects_trade_preview(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "disabled"},
    ).json()["run_id"]

    response = client.post(
        "/api/trades/preview",
        json={"run_id": run_id, "symbol": "NVDA", "side": "buy", "notional": 1000},
    )

    assert response.status_code == 403


def test_trade_preview_api_enforces_symbolic_policy_before_creating_intent(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(database_url))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "paper"},
    ).json()["run_id"]
    _, session_factory = create_session_factory(database_url)
    with session_factory() as session:
        before_intents = session.exec(
            select(TradeIntentRecord).where(TradeIntentRecord.run_id == run_id)
        ).all()

    response = client.post(
        "/api/trades/preview",
        json={"run_id": run_id, "symbol": "NVDA", "side": "buy", "notional": 25_000},
    )

    assert response.status_code == 400
    assert "position concentration" in response.json()["detail"]
    with session_factory() as session:
        after_intents = session.exec(
            select(TradeIntentRecord).where(TradeIntentRecord.run_id == run_id)
        ).all()
        assert len(after_intents) == len(before_intents)


def test_disabled_run_rejects_trade_approval(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(database_url))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "disabled"},
    ).json()["run_id"]
    _, session_factory = create_session_factory(database_url)
    repo = UiRepository(session_factory)
    intent = repo.create_trade_intent(
        run_id=run_id, symbol="NVDA", side="buy", notional=1000
    )

    response = client.post(
        f"/api/trades/{intent.intent_id}/approve", json={"actor": "local-user"}
    )

    assert response.status_code == 403
    assert not repo.has_approval(intent.intent_id)


def test_trade_ticket_preview_invalid_side_returns_validation_error(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "paper"},
    ).json()["run_id"]

    response = client.post(
        "/api/trades/preview",
        json={"run_id": run_id, "symbol": "NVDA", "side": "hold", "notional": 1000},
    )

    assert response.status_code == 422


def test_trade_ticket_duplicate_submit_reconciles_original_order(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "paper"},
    ).json()["run_id"]
    intent_id = client.post(
        "/api/trades/preview",
        json={"run_id": run_id, "symbol": "NVDA", "side": "buy", "notional": 1000},
    ).json()["intent_id"]

    client.post(f"/api/trades/{intent_id}/approve", json={"actor": "local-user"})
    submitted = client.post(f"/api/trades/{intent_id}/submit")
    duplicate = client.post(f"/api/trades/{intent_id}/submit")

    assert submitted.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["broker_order_id"] == submitted.json()["broker_order_id"]


def test_exact_ticket_hash_recovery_partial_fill_and_cancel_are_persisted(tmp_path):
    from tradingagents.ui.brokers.fake import FakePaperBroker
    broker = FakePaperBroker()
    database_url = f"sqlite:///{tmp_path/'exact.db'}"
    providers = {"fixture-paper-broker": broker}
    client = TestClient(create_app(database_url, broker_providers=providers))
    run_id = client.post("/api/runs", json={"ticker":"AAA", "trade_date":"2026-04-30", "broker_mode":"paper"}).json()["run_id"]
    preview = client.post("/api/trades/preview", json={"run_id":run_id, "symbol":"AAA", "side":"buy", "notional":650}).json()
    intent_id = preview["intent_id"]
    assert preview["exact_order"]["quantity"] == 6 and preview["evidence_kind"] == "fixture"
    mismatch = client.post(f"/api/trades/{intent_id}/approve", json={"actor":"operator", "expected_order_hash":"0"*64})
    assert mismatch.status_code == 400 and "displayed exact order" in mismatch.json()["detail"]
    assert client.post(f"/api/trades/{intent_id}/submit").status_code == 403
    assert client.post(f"/api/trades/{intent_id}/approve", json={"actor":"operator", "expected_order_hash":preview["order_hash"]}).status_code == 200
    assert client.post(f"/api/trades/{intent_id}/submit").json()["status"] == "accepted"
    broker.fill(intent_id, 2)
    restarted = TestClient(create_app(database_url, broker_providers=providers))
    assert restarted.post(f"/api/trades/{intent_id}/reconcile").json()["status"] == "partially_filled"
    history = restarted.get(f"/api/trades/{intent_id}/execution").json()
    assert history["order"]["content_hash"] == preview["order_hash"]
    assert history["attempt"]["observation"]["filled_quantity"] == "2"
    assert restarted.post(f"/api/trades/{intent_id}/cancel", json={"actor":"operator"}).json()["status"] == "canceled"
    saved = restarted.get(f"/api/trades/{intent_id}/execution").json()
    assert saved["order"]["state"] == "canceled" and len(saved["events"]) >= 6
    assert broker.economic_orders == 1
    assert restarted.get("/api/trades/absent/execution").status_code == 404
