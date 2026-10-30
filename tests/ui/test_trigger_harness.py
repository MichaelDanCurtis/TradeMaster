from pathlib import Path

from fastapi.testclient import TestClient

from tradingagents.ui.api import create_app
from tradingagents.ui.models import AgentTriggerRecord
from tradingagents.ui.trigger_harness import evaluate_agent_triggers


def _trigger(
    trigger_type: str,
    *,
    condition: dict[str, object],
    symbol: str | None = "NVDA",
    enabled: bool = True,
    trigger_id: str | None = None,
) -> AgentTriggerRecord:
    return AgentTriggerRecord(
        trigger_id=trigger_id or f"trigger_{trigger_type}",
        name=f"{trigger_type} wakeup",
        room_id="market",
        trigger_type=trigger_type,
        target_agent=f"{trigger_type}-agent",
        symbol=symbol,
        condition=condition,
        workflow_id=f"workflow_{trigger_type}",
        enabled=enabled,
        payload={"advisory_only": True},
    )


def test_harness_evaluates_all_supported_trigger_types_without_mutating_records():
    triggers = [
        _trigger("time", condition={"cadence": "hourly"}, trigger_id="trigger_time"),
        _trigger(
            "price",
            condition={"field": "price", "operator": ">=", "value": 500},
            trigger_id="trigger_price",
        ),
        _trigger(
            "volume",
            condition={"field": "volume", "operator": ">", "value": 1_000_000},
            trigger_id="trigger_volume",
        ),
        _trigger(
            "sentiment_flip",
            condition={"from": "positive", "to": "negative"},
            trigger_id="trigger_sentiment",
        ),
        _trigger(
            "report_event",
            condition={"event": "published", "report_type": "earnings"},
            trigger_id="trigger_report",
        ),
        _trigger(
            "risk_threshold",
            condition={"field": "risk_score", "operator": ">=", "value": 0.8},
            trigger_id="trigger_risk",
        ),
        _trigger(
            "compliance_flag",
            condition={"flag": "restricted_list", "severity": "blocker"},
            trigger_id="trigger_compliance",
        ),
    ]
    event = {
        "symbol": "nvda",
        "time": {"cadence": "hourly"},
        "price": 501,
        "volume": 1_250_000,
        "previous_sentiment": "positive",
        "sentiment": "negative",
        "report_event": "published",
        "report_type": "earnings",
        "risk_score": 0.91,
        "compliance_flags": [{"flag": "restricted_list", "severity": "blocker"}],
    }

    result = evaluate_agent_triggers(triggers, event)

    assert result.evaluated_count == 7
    assert [trigger.trigger_id for trigger in result.fired] == [
        "trigger_time",
        "trigger_price",
        "trigger_volume",
        "trigger_sentiment",
        "trigger_report",
        "trigger_risk",
        "trigger_compliance",
    ]
    assert all(fired.payload["advisory_only"] is True for fired in result.fired)
    assert all(trigger.last_fired_at is None for trigger in triggers)


def test_harness_filters_disabled_symbol_mismatches_and_non_matching_conditions():
    triggers = [
        _trigger(
            "price",
            condition={"field": "price", "operator": ">=", "value": 500},
            enabled=False,
            trigger_id="disabled",
        ),
        _trigger(
            "price",
            condition={"field": "price", "operator": ">=", "value": 500},
            symbol="MSFT",
            trigger_id="wrong_symbol",
        ),
        _trigger(
            "price",
            condition={"field": "price", "operator": ">=", "value": 900},
            trigger_id="wrong_price",
        ),
        _trigger(
            "price",
            condition={"field": "price", "operator": ">=", "value": "not-a-number"},
            trigger_id="malformed_price",
        ),
        _trigger(
            "price",
            condition={"field": "price", "operator": ">=", "value": 500},
            trigger_id="matching",
        ),
    ]

    result = evaluate_agent_triggers(triggers, {"symbol": "NVDA", "price": 650})

    assert [trigger.trigger_id for trigger in result.fired] == ["matching"]
    assert result.evaluated_count == 3


def test_agent_trigger_harness_endpoint_returns_fired_triggers_without_live_state(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    created = client.post(
        "/api/agent-triggers",
        json={
            "name": "NVDA price wakeup",
            "room_id": "market",
            "trigger_type": "price",
            "target_agent": "risk-agent",
            "symbol": "NVDA",
            "condition": {"field": "price", "operator": ">=", "value": 500},
            "workflow_id": "workflow_price",
            "enabled": True,
            "payload": {"paper_advisory_only": True},
        },
    )

    response = client.post(
        "/api/agent-triggers/evaluate",
        json={"event": {"symbol": "nvda", "price": 512}},
    )
    persisted = client.get("/api/agent-triggers?symbol=NVDA").json()["triggers"][0]

    assert created.status_code == 200
    assert response.status_code == 200
    body = response.json()
    assert body["paper_advisory_only"] is True
    assert body["fired_count"] == 1
    assert body["fired"][0]["trigger_id"] == created.json()["trigger_id"]
    assert body["fired"][0]["target_agent"] == "risk-agent"
    assert persisted["last_fired_at"] is None
