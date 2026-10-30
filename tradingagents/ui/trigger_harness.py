from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from collections.abc import Iterable, Mapping

from tradingagents.ui.models import AgentTriggerRecord


SUPPORTED_TRIGGER_TYPES = {
    "time",
    "price",
    "volume",
    "sentiment_flip",
    "report_event",
    "risk_threshold",
    "compliance_flag",
}


@dataclass(frozen=True)
class FiredAgentTrigger:
    trigger_id: str
    name: str
    room_id: str
    trigger_type: str
    target_agent: str
    symbol: str | None
    workflow_id: str | None
    reason: str
    condition: dict[str, Any]
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "name": self.name,
            "room_id": self.room_id,
            "trigger_type": self.trigger_type,
            "target_agent": self.target_agent,
            "symbol": self.symbol,
            "workflow_id": self.workflow_id,
            "reason": self.reason,
            "condition": self.condition,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class TriggerHarnessResult:
    fired: tuple[FiredAgentTrigger, ...]
    evaluated_count: int
    skipped_count: int
    event: dict[str, Any]

    @property
    def fired_count(self) -> int:
        return len(self.fired)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_advisory_only": True,
            "fired_count": self.fired_count,
            "evaluated_count": self.evaluated_count,
            "skipped_count": self.skipped_count,
            "event": self.event,
            "fired": [trigger.to_dict() for trigger in self.fired],
        }


def evaluate_agent_triggers(
    triggers: Iterable[AgentTriggerRecord],
    event: Mapping[str, Any],
) -> TriggerHarnessResult:
    """Evaluate local advisory wakeup triggers without mutating persisted state."""
    event_payload = dict(event)
    fired: list[FiredAgentTrigger] = []
    evaluated_count = 0
    skipped_count = 0
    for trigger in triggers:
        if not _is_candidate(trigger, event_payload):
            skipped_count += 1
            continue
        evaluated_count += 1
        reason = _match_reason(trigger, event_payload)
        if reason is None:
            continue
        fired.append(
            FiredAgentTrigger(
                trigger_id=trigger.trigger_id,
                name=trigger.name,
                room_id=trigger.room_id,
                trigger_type=trigger.trigger_type,
                target_agent=trigger.target_agent,
                symbol=trigger.symbol,
                workflow_id=trigger.workflow_id,
                reason=reason,
                condition=dict(trigger.condition or {}),
                payload=dict(trigger.payload or {}),
            )
        )
    return TriggerHarnessResult(
        fired=tuple(fired),
        evaluated_count=evaluated_count,
        skipped_count=skipped_count,
        event=event_payload,
    )


def _is_candidate(trigger: AgentTriggerRecord, event: Mapping[str, Any]) -> bool:
    if not trigger.enabled:
        return False
    if trigger.trigger_type not in SUPPORTED_TRIGGER_TYPES:
        return False
    requested_type = _event_trigger_type(event)
    if requested_type is not None and requested_type != trigger.trigger_type:
        return False
    if trigger.symbol is None:
        return True
    event_symbol = event.get("symbol")
    return isinstance(event_symbol, str) and event_symbol.upper() == trigger.symbol.upper()


def _event_trigger_type(event: Mapping[str, Any]) -> str | None:
    value = event.get("trigger_type", event.get("type"))
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _match_reason(trigger: AgentTriggerRecord, event: Mapping[str, Any]) -> str | None:
    condition = dict(trigger.condition or {})
    match trigger.trigger_type:
        case "time":
            return _match_mapping_condition(condition, _with_nested(event, "time"), "time condition matched")
        case "price":
            return _match_numeric_condition(condition, event, default_field="price", label="price")
        case "volume":
            return _match_numeric_condition(condition, event, default_field="volume", label="volume")
        case "sentiment_flip":
            return _match_sentiment_flip(condition, event)
        case "report_event":
            return _match_report_event(condition, event)
        case "risk_threshold":
            return _match_numeric_condition(condition, event, default_field="risk_score", label="risk threshold")
        case "compliance_flag":
            return _match_compliance_flag(condition, event)
    return None


def _with_nested(event: Mapping[str, Any], key: str) -> dict[str, Any]:
    merged = dict(event)
    nested = event.get(key)
    if isinstance(nested, Mapping):
        merged.update(nested)
    return merged


def _match_mapping_condition(
    condition: Mapping[str, Any],
    event: Mapping[str, Any],
    reason: str,
) -> str | None:
    if all(_values_equal(event.get(key), value) for key, value in condition.items()):
        return reason
    return None


def _match_numeric_condition(
    condition: Mapping[str, Any],
    event: Mapping[str, Any],
    *,
    default_field: str,
    label: str,
) -> str | None:
    field = str(condition.get("field") or default_field)
    actual = _as_decimal(event.get(field))
    if actual is None:
        return None

    operator, expected, has_expected = _numeric_operator_and_expected(condition)
    if not has_expected:
        return f"{label} observed"
    if expected is None:
        return None
    if _compare(actual, operator, expected):
        return f"{label} {field} {operator} {expected}"
    return None


def _numeric_operator_and_expected(
    condition: Mapping[str, Any],
) -> tuple[str, Decimal | None, bool]:
    if "operator" in condition and "value" in condition:
        return str(condition["operator"]), _as_decimal(condition["value"]), True
    if "threshold" in condition:
        return str(condition.get("operator") or ">="), _as_decimal(condition["threshold"]), True
    if "above" in condition:
        return ">", _as_decimal(condition["above"]), True
    if "below" in condition:
        return "<", _as_decimal(condition["below"]), True
    if "min" in condition:
        return ">=", _as_decimal(condition["min"]), True
    if "max" in condition:
        return "<=", _as_decimal(condition["max"]), True
    if "equals" in condition:
        return "==", _as_decimal(condition["equals"]), True
    return ">=", None, False


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _compare(actual: Decimal, operator: str, expected: Decimal | None) -> bool:
    if expected is None:
        return False
    match operator:
        case ">" | "above":
            return actual > expected
        case ">=" | "gte" | "at_or_above":
            return actual >= expected
        case "<" | "below":
            return actual < expected
        case "<=" | "lte" | "at_or_below":
            return actual <= expected
        case "==" | "=" | "eq":
            return actual == expected
        case "!=" | "ne":
            return actual != expected
    return False


def _match_sentiment_flip(condition: Mapping[str, Any], event: Mapping[str, Any]) -> str | None:
    previous = event.get("previous_sentiment", event.get("from_sentiment"))
    current = event.get("sentiment", event.get("current_sentiment", event.get("to_sentiment")))
    if not isinstance(previous, str) or not isinstance(current, str):
        return None
    if previous.strip().lower() == current.strip().lower():
        return None
    expected_from = condition.get("from")
    expected_to = condition.get("to", condition.get("sentiment"))
    if expected_from is not None and not _values_equal(previous, expected_from):
        return None
    if expected_to is not None and not _values_equal(current, expected_to):
        return None
    return f"sentiment flipped from {previous} to {current}"


def _match_report_event(condition: Mapping[str, Any], event: Mapping[str, Any]) -> str | None:
    report_event = event.get("report_event", event.get("event"))
    if "event" in condition and not _values_equal(report_event, condition["event"]):
        return None
    remaining = {key: value for key, value in condition.items() if key != "event"}
    if not _match_mapping_condition(remaining, event, "report event matched"):
        return None
    if report_event is None and "event" not in condition:
        return None
    return f"report event {report_event} matched"


def _match_compliance_flag(condition: Mapping[str, Any], event: Mapping[str, Any]) -> str | None:
    flags = _compliance_flags(event)
    if not flags:
        return None
    if not condition:
        return "compliance flag observed"
    for flag in flags:
        if all(_values_equal(flag.get(key), value) for key, value in condition.items()):
            return f"compliance flag {flag.get('flag', flag.get('name', 'observed'))} matched"
    return None


def _compliance_flags(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_flags = event.get("compliance_flags", event.get("compliance_flag", event.get("flag")))
    if isinstance(raw_flags, list):
        return [dict(flag) for flag in raw_flags if isinstance(flag, Mapping)]
    if isinstance(raw_flags, Mapping):
        return [dict(raw_flags)]
    if isinstance(raw_flags, str):
        return [{"flag": raw_flags}]
    return []


def _values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.strip().lower() == expected.strip().lower()
    return actual == expected
