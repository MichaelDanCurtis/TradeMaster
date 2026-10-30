"""Background poller and per-watcher checker for the Watcher primitive."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable

from tradingagents.ui.market_data.base import MarketDataProvider
from tradingagents.ui.models import WatcherFireRecord, WatcherRecord
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.watchers.conditions import (
    ConditionEvaluation,
    evaluate_condition,
    fetch_observation,
)


_LOG = logging.getLogger(__name__)


POLL_INTERVAL_SECONDS: int = 30
DEFAULT_COOLDOWN_SECONDS: int = 300


MarketDataResolver = Callable[[], tuple[MarketDataProvider | None, str | None]]


def _cooldown_seconds(watcher: WatcherRecord) -> int:
    raw = watcher.payload.get("cooldown_seconds") if watcher.payload else None
    if raw is None:
        return DEFAULT_COOLDOWN_SECONDS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_COOLDOWN_SECONDS
    return max(0, value)


def _in_cooldown(watcher: WatcherRecord, *, now: datetime) -> bool:
    if watcher.last_fired_at is None:
        return False
    last = watcher.last_fired_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = (now - last).total_seconds()
    return elapsed < _cooldown_seconds(watcher)


def check_watcher_once(
    repo: UiRepository,
    watcher: WatcherRecord,
    provider: MarketDataProvider,
    *,
    feed: str | None = None,
    record_fires: bool = True,
    now: datetime | None = None,
) -> tuple[ConditionEvaluation, WatcherFireRecord | None, bool]:
    """Evaluate a single watcher; optionally persist the fire.

    Returns ``(evaluation, fire_record_or_None, in_cooldown)``. The fire is
    suppressed if the watcher is currently in cooldown.
    """
    observed_value, observation_payload = fetch_observation(
        provider,
        symbol=watcher.symbol,
        condition_type=watcher.condition_type,
        feed=feed,
    )
    evaluation = evaluate_condition(
        condition_type=watcher.condition_type,
        threshold=watcher.threshold,
        observed_value=observed_value,
        payload=observation_payload,
    )
    current_time = now or datetime.now(timezone.utc)
    cooldown = _in_cooldown(watcher, now=current_time)
    fire: WatcherFireRecord | None = None
    if evaluation.fired and watcher.enabled and record_fires and not cooldown:
        fire = repo.record_watcher_fire(
            watcher_id=watcher.watcher_id,
            symbol=watcher.symbol,
            condition_type=watcher.condition_type,
            threshold=watcher.threshold,
            observed_value=observed_value,
            payload=observation_payload,
        )
    return evaluation, fire, cooldown


async def _run_poll(
    repo: UiRepository,
    resolver: MarketDataResolver,
) -> None:
    try:
        provider, feed = resolver()
    except Exception as exc:  # noqa: BLE001 - log + skip; loop should keep running
        _LOG.warning("watcher firing loop: provider resolution failed: %s", exc)
        return
    if provider is None:
        _LOG.debug("watcher firing loop: no market data provider configured; skipping tick")
        return
    try:
        watchers = repo.list_watchers(enabled=True, limit=500)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("watcher firing loop: list_watchers failed: %s", exc)
        return
    for watcher in watchers:
        try:
            check_watcher_once(repo, watcher, provider, feed=feed)
        except Exception as exc:  # noqa: BLE001 - one bad symbol shouldn't kill loop
            _LOG.warning(
                "watcher firing loop: check failed for %s (%s): %s",
                watcher.watcher_id,
                watcher.symbol,
                exc,
            )


async def _firing_loop(
    repo: UiRepository,
    resolver: MarketDataResolver,
    *,
    interval_seconds: int,
    stop_event: asyncio.Event,
) -> None:
    _LOG.info("watcher firing loop started (interval=%ss)", interval_seconds)
    try:
        while not stop_event.is_set():
            await _run_poll(repo, resolver)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        _LOG.info("watcher firing loop cancelled")
        raise
    finally:
        _LOG.info("watcher firing loop exited")


def start_firing_loop(
    repo: UiRepository,
    resolver: MarketDataResolver,
    *,
    interval_seconds: int = POLL_INTERVAL_SECONDS,
) -> tuple[asyncio.Task[None], asyncio.Event]:
    """Start the background poller. Returns ``(task, stop_event)``.

    Caller is responsible for setting ``stop_event`` and awaiting the task on
    shutdown.
    """
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        _firing_loop(
            repo,
            resolver,
            interval_seconds=interval_seconds,
            stop_event=stop_event,
        ),
        name="watcher-firing-loop",
    )
    return task, stop_event
