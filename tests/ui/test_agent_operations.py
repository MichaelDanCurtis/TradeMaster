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


def test_repository_creates_lists_and_updates_agent_operations(tmp_path: Path):
    repo = _repo(tmp_path)

    created = repo.create_agent_operation(
        agent_id="agent_research_manager",
        agent_name="Research Manager",
        room_id="research",
        symbol="nvda",
        operation_type="research_report",
        authority="research_only",
        source_workflow_id="workflow_research",
        linked_run_id="run_123",
        payload={"prompt": "earnings refresh"},
    )
    completed = repo.update_agent_operation(
        created.operation_id,
        status="completed",
        payload={"report_id": "report_123"},
    )
    listed = repo.list_agent_operations(symbol="NVDA", status="completed")
    filtered_out = repo.list_agent_operations(room_id="market")

    assert created.operation_id.startswith("agentop_")
    assert created.symbol == "NVDA"
    assert created.status == "queued"
    assert created.authority == "research_only"
    assert completed.operation_id == created.operation_id
    assert completed.status == "completed"
    assert completed.payload == {"report_id": "report_123"}
    assert completed.completed_at is not None
    assert listed[0].operation_id == created.operation_id
    assert filtered_out == []


def test_repository_rejects_live_or_unsafe_execution_authority(tmp_path: Path):
    repo = _repo(tmp_path)

    with pytest.raises(ValueError, match="authority"):
        repo.create_agent_operation(
            agent_id="agent_live",
            agent_name="Live Trader",
            room_id="market",
            symbol="AAPL",
            operation_type="execution_preview",
            authority="live_trading",
        )

    with pytest.raises(ValueError, match="execution operations"):
        repo.create_agent_operation(
            agent_id="agent_execution",
            agent_name="Execution Agent",
            room_id="market",
            symbol="AAPL",
            operation_type="execution_preview",
            authority="research_only",
        )


def test_agent_operations_api_round_trip_and_complete(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/agent-operations",
        json={
            "agent_id": "agent_execution",
            "agent_name": "Execution Agent",
            "room_id": "market",
            "symbol": "msft",
            "operation_type": "execution_preview",
            "authority": "paper_only",
            "source_workflow_id": "workflow_execution",
            "linked_execution_program_id": "program_123",
            "payload": {"notional": 25000},
        },
    )
    operation = created.json()
    completed = client.post(
        f"/api/agent-operations/{operation['operation_id']}/complete",
        json={
            "linked_run_id": "run_456",
            "payload": {"preview": "ready"},
        },
    )
    listed = client.get(
        "/api/agent-operations",
        params={"symbol": "MSFT", "status": "completed"},
    )

    assert created.status_code == 200
    assert operation["operation_id"].startswith("agentop_")
    assert operation["symbol"] == "MSFT"
    assert operation["status"] == "queued"
    assert operation["authority"] == "paper_only"
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["linked_run_id"] == "run_456"
    assert completed.json()["payload"] == {"preview": "ready"}
    assert listed.status_code == 200
    assert listed.json()["operations"][0]["operation_id"] == operation["operation_id"]


def test_agent_operations_api_rejects_live_or_unsafe_execution_authority(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    live_response = client.post(
        "/api/agent-operations",
        json={
            "agent_id": "agent_live",
            "agent_name": "Live Trader",
            "room_id": "market",
            "symbol": "TSLA",
            "operation_type": "execution_preview",
            "authority": "live_trading",
        },
    )
    research_only_execution = client.post(
        "/api/agent-operations",
        json={
            "agent_id": "agent_execution",
            "agent_name": "Execution Agent",
            "room_id": "market",
            "symbol": "TSLA",
            "operation_type": "execution_preview",
            "authority": "research_only",
        },
    )

    assert live_response.status_code == 400
    assert "authority" in live_response.json()["detail"]
    assert research_only_execution.status_code == 400
    assert "execution operations" in research_only_execution.json()["detail"]
