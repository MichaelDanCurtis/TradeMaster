from pathlib import Path

from fastapi.testclient import TestClient

from tradingagents.ui.api import create_app
from tradingagents.ui.db import create_session_factory
from tradingagents.ui.repository import UiRepository


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

    assert by_id["simulated-market-data"]["status"] == "available"
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


def test_snapshot_endpoint_creates_manifest_for_local_sqlite(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(database_url))

    response = client.post(
        "/api/snapshots",
        json={"encryption_mode": "age", "offsite_target": "backblaze-b2"},
    )

    assert response.status_code == 200
    assert response.json()["storage_profile"] == "sqlite-local"
    assert response.json()["encryption_mode"] == "age"
    assert response.json()["manifest"]["files"][0]["path"] == str(tmp_path / "ui.db")
    assert len(response.json()["manifest"]["files"][0]["sha256"]) == 64


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
    assert submitted.json()["status"] == "submitted"


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


def test_trade_ticket_duplicate_submit_returns_controlled_error(tmp_path: Path):
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
    assert duplicate.status_code in (400, 403)
