"""Watcher primitive: persistent symbol rules that fire when conditions are met."""

from tradingagents.ui.watchers.conditions import (
    CONDITION_TYPES,
    ConditionEvaluation,
    evaluate_condition,
    fetch_observation,
)
from tradingagents.ui.watchers.firing_loop import (
    DEFAULT_COOLDOWN_SECONDS,
    POLL_INTERVAL_SECONDS,
    check_watcher_once,
    start_firing_loop,
)

__all__ = [
    "CONDITION_TYPES",
    "ConditionEvaluation",
    "DEFAULT_COOLDOWN_SECONDS",
    "POLL_INTERVAL_SECONDS",
    "check_watcher_once",
    "evaluate_condition",
    "fetch_observation",
    "start_firing_loop",
]
