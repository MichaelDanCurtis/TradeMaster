from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradingagents.ui.api import create_app
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.repository import UiRepository


def _repo(tmp_path: Path) -> UiRepository:
    db_url = f"sqlite:///{tmp_path / 'ui.db'}"
    engine, session_factory = create_session_factory(db_url)
    init_db(engine)
    return UiRepository(session_factory)


def test_portfolio_review_api_round_trip_and_filters(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/portfolio-reviews",
        json={
            "symbol": "nvda",
            "goals": "Compound capital",
            "horizon": "12 months",
            "risk_posture": "balanced",
            "sector_focus": "semiconductors",
            "constraints": "No margin",
            "liquidity_needs": "10% cash",
            "thesis": {"rating": "overweight"},
            "missing_provider_facts": ["tax lots"],
            "payload": {"source": "test"},
        },
    )
    listed = client.get("/api/portfolio-reviews", params={"symbol": "NVDA"})
    filtered_out = client.get("/api/portfolio-reviews", params={"status": "approved"})

    assert created.status_code == 200
    body = created.json()
    assert body["review_id"].startswith("preview_")
    assert body["symbol"] == "NVDA"
    assert body["room_id"] == "portfolio"
    assert body["status"] == "draft"
    assert body["thesis"] == {"rating": "overweight"}
    assert body["missing_provider_facts"] == ["tax lots"]
    assert listed.json()["reviews"][0]["review_id"] == body["review_id"]
    assert filtered_out.json()["reviews"] == []


def test_funding_allocation_review_api_round_trip(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/funding-allocation-reviews",
        json={
            "symbol": "msft",
            "source_thesis_id": "thesis_123",
            "execution_program_id": "program_123",
            "notional": 25000,
            "tracks": [{"name": "core", "notional": 15000}],
            "missing_provider_facts": ["available cash"],
            "approval_next_steps": ["portfolio approval"],
            "payload": {"rebalance": True},
        },
    )
    listed = client.get("/api/funding-allocation-reviews", params={"symbol": "MSFT"})

    assert created.status_code == 200
    body = created.json()
    assert body["review_id"].startswith("funding_")
    assert body["symbol"] == "MSFT"
    assert body["status"] == "draft"
    assert body["notional"] == 25000
    assert body["tracks"] == [{"name": "core", "notional": 15000}]
    assert body["approval_next_steps"] == ["portfolio approval"]
    assert listed.json()["reviews"][0]["review_id"] == body["review_id"]


def test_execution_program_api_round_trip_and_events(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/execution-programs",
        json={
            "symbol": "aapl",
            "source_thesis_id": "thesis_456",
            "algorithm": "dca_ladder",
            "trigger_points": [{"price": 180}],
            "circuit_breakers": [{"max_drawdown_percent": 4}],
            "missing_provider_facts": ["current spread"],
            "payload": {"preview": True},
        },
    )
    program = created.json()
    event = client.post(
        f"/api/execution-programs/{program['program_id']}/events",
        json={
            "event_type": "preview.generated",
            "summary": "Generated paper preview",
            "payload": {"steps": 3},
        },
    )
    events = client.get(f"/api/execution-programs/{program['program_id']}/events")
    listed = client.get("/api/execution-programs", params={"symbol": "AAPL"})

    assert created.status_code == 200
    assert program["program_id"].startswith("program_")
    assert program["symbol"] == "AAPL"
    assert program["state"] == "preview_ready"
    assert program["mode"] == "paper"
    assert program["approval_status"] == "required"
    assert program["live_submission_enabled"] is False
    assert event.status_code == 200
    assert event.json()["event_id"].startswith("progevt_")
    assert events.json()["events"][0]["summary"] == "Generated paper preview"
    assert listed.json()["programs"][0]["program_id"] == program["program_id"]


def test_execution_program_rejects_live_submission_enabled(tmp_path: Path):
    repo = _repo(tmp_path)

    with pytest.raises(ValueError, match="live_submission_enabled"):
        repo.create_execution_program(
            symbol="TSLA",
            algorithm="bracket_order",
            live_submission_enabled=True,
        )

    client = TestClient(create_app(f"sqlite:///{tmp_path / 'api.db'}"))
    response = client.post(
        "/api/execution-programs",
        json={
            "symbol": "TSLA",
            "algorithm": "bracket_order",
            "live_submission_enabled": True,
        },
    )

    assert response.status_code == 400
    assert "live_submission_enabled" in response.json()["detail"]
