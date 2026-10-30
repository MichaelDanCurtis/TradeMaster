from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timezone
from typing import Any, Protocol

from tradingagents.ui.events import RunConfig, RunCreated, RunEvent, RunStatus
from tradingagents.ui.repository import UiRepository


ANALYST_PROGRESS_NODES = {
    "market": "Market Analyst",
    "news": "News Analyst",
    "social": "Social Analyst",
    "fundamentals": "Fundamentals Analyst",
}

DOWNSTREAM_PROGRESS_NODES = [
    "Bull Researcher",
    "Bear Researcher",
    "Research Manager",
    "Trader",
    "Risk Manager",
    "Portfolio Manager",
]


@dataclass(frozen=True)
class RealRunResult:
    events: list[RunEvent]
    rating: str
    action: str
    thesis: str
    risk_notes: str | None = None


class RealRunRunner(Protocol):
    def __call__(self, run_id: str, config: RunConfig) -> RealRunResult: ...


class TradingRunService:
    def __init__(
        self,
        repository: UiRepository,
        real_runner: RealRunRunner | None = None,
    ) -> None:
        self._repository = repository
        self._real_runner = real_runner

    def start_run(self, config: RunConfig) -> RunCreated:
        run = self._repository.create_run(config)
        self._repository.start_observability_trace(
            run_id=run.run_id,
            metadata=self._trace_metadata(config),
        )
        if config.execution_mode == "real":
            if self._real_runner is None:
                self._append_real_run_not_configured_events(run.run_id, config)
                self._repository.update_observability_trace(
                    run.run_id,
                    status=RunStatus.FAILED.value,
                    metadata={"failure_reason": "real_runner_not_configured"},
                )
                return RunCreated(run_id=run.run_id, status=RunStatus.FAILED)
            return self._append_real_run_events(run.run_id, config)
        self._append_fake_events(run.run_id, config)
        self._repository.update_observability_trace(
            run.run_id,
            status=RunStatus.COMPLETED.value,
        )
        return RunCreated(run_id=run.run_id, status=RunStatus.COMPLETED)

    def list_events(self, run_id: str) -> list[RunEvent]:
        return self._repository.list_events(run_id)

    async def stream_sse(
        self,
        run_id: str,
        *,
        poll_interval: float = 1.0,
        heartbeat_every: float = 15.0,
    ) -> AsyncIterator[str]:
        """Tail run events as Server-Sent Events.

        Polls the repository at ``poll_interval`` seconds for events with
        sequence greater than the last one yielded. Emits ``:keepalive``
        comments at most every ``heartbeat_every`` seconds so proxies and
        browsers keep the connection open during quiet periods. Closes the
        stream once a terminal ``run.completed`` / ``run.failed`` /
        ``run.canceled`` event has been emitted.
        """

        terminal_types = {"run.completed", "run.failed", "run.canceled"}
        last_sequence = 0
        last_emit_at = time.monotonic()

        while True:
            events = self._repository.list_events_since(
                run_id, after_sequence=last_sequence
            )
            terminal = False
            for event in events:
                data = json.dumps(
                    self._serialize_event(event), separators=(",", ":")
                )
                yield f"event: {event.type}\ndata: {data}\n\n"
                last_sequence = event.sequence
                last_emit_at = time.monotonic()
                if event.type in terminal_types:
                    terminal = True
            if terminal:
                return

            if time.monotonic() - last_emit_at >= heartbeat_every:
                yield ":keepalive\n\n"
                last_emit_at = time.monotonic()

            await asyncio.sleep(poll_interval)

    def queue_real_run(self, config: RunConfig) -> RunCreated:
        run = self._repository.create_run(config)
        self._repository.start_observability_trace(
            run_id=run.run_id,
            metadata=self._trace_metadata(config),
        )
        self._repository.set_run_status(run.run_id, RunStatus.RUNNING)
        next_sequence = self._append_real_run_start_events(run.run_id, config, start_sequence=1)
        self._append_real_run_progress_events(
            run.run_id,
            config,
            start_sequence=next_sequence,
            runner_progress=self._runner_progress_metadata(),
        )
        return RunCreated(run_id=run.run_id, status=RunStatus.RUNNING)

    def complete_queued_real_run(self, run_id: str, config: RunConfig) -> RunCreated:
        next_sequence = self._next_event_sequence(run_id)
        if self._real_runner is None:
            self._append_real_run_not_configured_events(run_id, config)
            self._repository.update_observability_trace(
                run_id,
                status=RunStatus.FAILED.value,
                metadata={"failure_reason": "real_runner_not_configured"},
            )
            return RunCreated(run_id=run_id, status=RunStatus.FAILED)
        return self._complete_real_run_events(run_id, config, next_sequence)

    def fail_interrupted_runs(self, *, reason: str = "server_restart") -> int:
        failed_count = 0
        for run in self._repository.list_runs():
            if run.status != RunStatus.RUNNING.value:
                continue
            next_sequence = self._next_event_sequence(run.run_id)
            self._append_events(
                run.run_id,
                [
                    RunEvent(
                        run_id=run.run_id,
                        sequence=next_sequence,
                        type="run.failed",
                        node=None,
                        message="Run was interrupted before completion.",
                        payload={
                            "status": RunStatus.FAILED.value,
                            "reason": reason,
                        },
                    )
                ],
                start_sequence=next_sequence,
            )
            self._repository.set_run_status(run.run_id, RunStatus.FAILED)
            self._repository.update_observability_trace(
                run.run_id,
                status=RunStatus.FAILED.value,
                metadata={"failure_reason": reason},
            )
            failed_count += 1
        return failed_count

    def _append_real_run_events(self, run_id: str, config: RunConfig) -> RunCreated:
        self._repository.set_run_status(run_id, RunStatus.RUNNING)
        next_sequence = self._append_real_run_start_events(run_id, config, start_sequence=1)
        return self._complete_real_run_events(run_id, config, next_sequence)

    def _complete_real_run_events(
        self,
        run_id: str,
        config: RunConfig,
        next_sequence: int,
    ) -> RunCreated:
        try:
            result = self._real_runner(run_id, config)
        except Exception as exc:
            self._append_events(
                run_id,
                [
                    RunEvent(
                        run_id=run_id,
                        sequence=next_sequence,
                        type="run.failed",
                        node=None,
                        message="Real TradingAgents execution failed.",
                        payload={
                            "status": RunStatus.FAILED.value,
                            "reason": "real_runner_exception",
                            "error": str(exc),
                        },
                    )
                ],
                start_sequence=next_sequence,
            )
            self._repository.set_run_status(run_id, RunStatus.FAILED)
            self._repository.update_observability_trace(
                run_id,
                status=RunStatus.FAILED.value,
                metadata={
                    "failure_reason": "real_runner_exception",
                    "error": str(exc),
                },
            )
            return RunCreated(run_id=run_id, status=RunStatus.FAILED)

        next_sequence = self._append_events(
            run_id,
            result.events,
            start_sequence=next_sequence,
        )
        self._repository.store_decision(
            run_id=run_id,
            rating=result.rating,
            action=result.action,
            thesis=result.thesis,
            risk_notes=result.risk_notes,
        )
        # Subscribers may read the trace as soon as run.completed is visible.
        # Persist the terminal metadata and status before publishing that event.
        self._repository.update_observability_trace(
            run_id,
            status=RunStatus.COMPLETED.value,
            metadata={"final_rating": result.rating, "final_action": result.action},
        )
        self._repository.set_run_status(run_id, RunStatus.COMPLETED)
        self._append_events(
            run_id,
            [
                RunEvent(
                    run_id=run_id,
                    sequence=next_sequence,
                    type="run.completed",
                    node=None,
                    message="Completed real TradingAgents run.",
                    payload={"status": RunStatus.COMPLETED.value},
                )
            ],
            start_sequence=next_sequence,
        )
        return RunCreated(run_id=run_id, status=RunStatus.COMPLETED)

    def _append_real_run_start_events(
        self,
        run_id: str,
        config: RunConfig,
        *,
        start_sequence: int,
    ) -> int:
        return self._append_events(
            run_id,
            [
                RunEvent(
                    run_id=run_id,
                    sequence=start_sequence,
                    type="run.created",
                    node=None,
                    message=f"Created real TradingAgents run for {config.ticker}.",
                    payload={
                        "ticker": config.ticker,
                        "trade_date": config.trade_date,
                        "execution_mode": config.execution_mode,
                    },
                ),
                RunEvent(
                    run_id=run_id,
                    sequence=start_sequence + 1,
                    type="run.started",
                    node=None,
                    message="Started real TradingAgents execution.",
                    payload={
                        "llm_provider": config.llm_provider,
                        "quick_model": config.quick_model,
                        "deep_model": config.deep_model,
                    },
                ),
            ],
            start_sequence=start_sequence,
        )

    def _append_real_run_progress_events(
        self,
        run_id: str,
        config: RunConfig,
        *,
        start_sequence: int,
        runner_progress: tuple[str, str],
    ) -> int:
        runner_label, runner_source = runner_progress
        selected_analysts = set(config.analysts)
        nodes = [
            node
            for analyst, node in ANALYST_PROGRESS_NODES.items()
            if analyst in selected_analysts
        ] + DOWNSTREAM_PROGRESS_NODES
        return self._append_events(
            run_id,
            [
                RunEvent(
                    run_id=run_id,
                    sequence=start_sequence + index,
                    type="agent.started",
                    node=node,
                    message=f"{node} queued in the {runner_label}.",
                    payload={
                        "source": runner_source,
                        "status": "queued",
                        "ticker": config.ticker,
                        "runner": runner_label,
                    },
                )
                for index, node in enumerate(nodes)
            ],
            start_sequence=start_sequence,
        )

    def _runner_progress_metadata(self) -> tuple[str, str]:
        if self._real_runner is not None and self._real_runner.__class__.__name__ == "TradingAgentsGraphRunner":
            return "full TradingAgents graph", "tradingagents-graph"
        return "safe synthesis runner", "safe-synthesis-runner"

    def _append_real_run_not_configured_events(self, run_id: str, config: RunConfig) -> None:
        events: list[dict[str, Any]] = [
            {
                "type": "run.created",
                "node": None,
                "message": f"Created real TradingAgents run for {config.ticker}.",
                "payload": {
                    "ticker": config.ticker,
                    "trade_date": config.trade_date,
                    "execution_mode": config.execution_mode,
                },
            },
            {
                "type": "run.started",
                "node": None,
                "message": "Real TradingAgents execution requested.",
                "payload": {
                    "llm_provider": config.llm_provider,
                    "quick_model": config.quick_model,
                    "deep_model": config.deep_model,
                },
            },
            {
                "type": "run.failed",
                "node": None,
                "message": "Real TradingAgents execution is not configured. Configure LLM and data providers first.",
                "payload": {
                    "status": RunStatus.FAILED.value,
                    "reason": "real_runner_not_configured",
                },
            },
        ]
        self._repository.set_run_status(run_id, RunStatus.RUNNING)
        for sequence, event in enumerate(events, start=1):
            self._repository.append_event(
                RunEvent(
                    run_id=run_id,
                    sequence=sequence,
                    type=event["type"],
                    node=event["node"],
                    message=event["message"],
                    payload=event["payload"],
                )
            )
        self._repository.set_run_status(run_id, RunStatus.FAILED)

    def _append_fake_events(self, run_id: str, config: RunConfig) -> None:
        analyst_events = [
            (
                "Market Analyst",
                "market",
                "simulated-market-data",
                "fake_market_snapshot",
                "Updated simulated market report.",
            ),
            (
                "News Analyst",
                "news",
                "simulated-news",
                "fake_news_scan",
                "Updated simulated news report.",
            ),
            (
                "Social Analyst",
                "social",
                "simulated-social",
                "fake_social_scan",
                "Updated simulated social report.",
            ),
            (
                "Fundamentals Analyst",
                "fundamentals",
                "simulated-fundamentals",
                "fake_fundamentals_snapshot",
                "Updated simulated fundamentals report.",
            ),
        ]
        fake_events: list[dict[str, Any]] = [
            {
                "type": "run.created",
                "node": None,
                "message": f"Created simulated run for {config.ticker}.",
                "payload": {
                    "ticker": config.ticker,
                    "providers": {
                        "brokerage": "fake-paper-broker"
                        if config.broker_mode == "paper"
                        else "disabled",
                        "llm": config.llm_provider,
                        "market_data": "simulated-market-data",
                    },
                },
            },
            {
                "type": "run.started",
                "node": None,
                "message": "Started simulated TradingAgents run.",
                "payload": {"trade_date": config.trade_date},
            },
        ]
        for node, analyst, provider, tool, report_message in analyst_events:
            fake_events.extend(
                [
                    {
                        "type": "agent.started",
                        "node": node,
                        "message": f"{node} started.",
                        "payload": {"analyst": analyst},
                    },
                    {
                        "type": "tool.called",
                        "node": node,
                        "message": f"Fetched {analyst} context from {provider}.",
                        "payload": {"provider": provider, "tool": tool},
                    },
                    {
                        "type": "report.updated",
                        "node": node,
                        "message": report_message,
                        "payload": {"section": analyst},
                    },
                ]
            )
        fake_events.extend(
            [
                {
                    "type": "agent.started",
                    "node": "Research Manager",
                    "message": "Research Manager started.",
                    "payload": {"agent": "research_manager"},
                },
                {
                    "type": "report.updated",
                    "node": "Research Manager",
                    "message": "Synthesized simulated bull and bear research.",
                    "payload": {"section": "research"},
                },
                {
                    "type": "agent.started",
                    "node": "Risk Manager",
                    "message": "Risk Manager started.",
                    "payload": {"agent": "risk_manager"},
                },
                {
                    "type": "report.updated",
                    "node": "Risk Manager",
                    "message": "Updated simulated risk debate.",
                    "payload": {"section": "risk"},
                },
                {
                    "type": "agent.started",
                    "node": "Portfolio Manager",
                    "message": "Portfolio Manager started.",
                    "payload": {"agent": "portfolio_manager"},
                },
            ]
        )
        fake_events.append(
            {
                "type": "decision.created",
                "node": "Portfolio Manager",
                "message": "Created simulated decision.",
                "payload": {"rating": "Overweight", "action": "Buy"},
            }
        )
        if config.broker_mode == "paper":
            fake_events.append(
                {
                    "type": "trade.previewed",
                    "node": "Broker",
                    "message": "Previewed simulated paper trade.",
                    "payload": {
                        "provider": "fake-paper-broker",
                        "side": "buy",
                        "symbol": config.ticker,
                    },
                }
            )
        fake_events.append(
            {
                "type": "run.completed",
                "node": None,
                "message": "Completed simulated TradingAgents run.",
                "payload": {"status": RunStatus.COMPLETED.value},
            }
        )

        self._repository.set_run_status(run_id, RunStatus.RUNNING)
        for sequence, event in enumerate(fake_events, start=1):
            self._repository.append_event(
                RunEvent(
                    run_id=run_id,
                    sequence=sequence,
                    type=event["type"],
                    node=event["node"],
                    message=event["message"],
                    payload=event["payload"],
                )
            )

        self._repository.store_decision(
            run_id=run_id,
            rating="Overweight",
            action="Buy",
            thesis=f"{config.ticker} has a constructive simulated setup for UI testing.",
            risk_notes="This is fake run output. Use paper trading only.",
        )
        if config.broker_mode == "paper":
            self._repository.create_trade_intent(
                run_id=run_id,
                symbol=config.ticker,
                side="buy",
                notional=10000,
            )
        self._repository.set_run_status(run_id, RunStatus.COMPLETED)

    def _append_events(
        self,
        run_id: str,
        events: list[RunEvent],
        *,
        start_sequence: int,
    ) -> int:
        next_sequence = start_sequence
        for event in events:
            self._repository.append_event(
                event.model_copy(
                    update={
                        "run_id": run_id,
                        "sequence": next_sequence,
                    }
                )
            )
            next_sequence += 1
        return next_sequence

    def _next_event_sequence(self, run_id: str) -> int:
        events = self._repository.list_events(run_id)
        if not events:
            return 1
        return max(event.sequence for event in events) + 1

    @staticmethod
    def _serialize_event(event: RunEvent) -> dict[str, Any]:
        created_at = event.created_at.astimezone(timezone.utc)
        return {
            "run_id": event.run_id,
            "sequence": event.sequence,
            "type": event.type,
            "node": event.node,
            "message": event.message,
            "payload": event.payload,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
        }

    def _trace_metadata(self, config: RunConfig) -> dict[str, Any]:
        metadata = {
            "ticker": config.ticker,
            "trade_date": config.trade_date,
            "execution_mode": config.execution_mode,
            "llm_provider": config.llm_provider,
            "quick_model": config.quick_model,
            "deep_model": config.deep_model,
            "broker_mode": config.broker_mode,
            "checkpoint": config.checkpoint,
            "analysts": list(config.analysts),
        }
        # The graph runner resolves the research_llm provider role at run time
        # and overrides llm_provider/quick/deep — record the RESOLVED values
        # (e.g. github-copilot-oauth / gpt-4o-mini / gpt-4o) instead of the
        # inert RunConfig defaults so the trace surface is truthful.
        resolver = getattr(self._real_runner, "resolved_llm_metadata", None)
        if callable(resolver):
            try:
                metadata.update(resolver(config))
            except Exception:  # noqa: BLE001 — metadata must never block run creation
                pass
        return metadata
