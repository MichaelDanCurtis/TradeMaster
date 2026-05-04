from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timezone
from typing import Any, Protocol

from tradingagents.ui.events import RunConfig, RunCreated, RunEvent, RunStatus
from tradingagents.ui.repository import UiRepository


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
        if config.execution_mode == "real":
            if self._real_runner is None:
                self._append_real_run_not_configured_events(run.run_id, config)
                return RunCreated(run_id=run.run_id, status=RunStatus.FAILED)
            return self._append_real_run_events(run.run_id, config)
        self._append_fake_events(run.run_id, config)
        return RunCreated(run_id=run.run_id, status=RunStatus.COMPLETED)

    def list_events(self, run_id: str) -> list[RunEvent]:
        return self._repository.list_events(run_id)

    def stream_sse(self, run_id: str) -> Iterator[str]:
        for event in self.list_events(run_id):
            data = json.dumps(self._serialize_event(event), separators=(",", ":"))
            yield f"event: {event.type}\ndata: {data}\n\n"

    def _append_real_run_events(self, run_id: str, config: RunConfig) -> RunCreated:
        self._repository.set_run_status(run_id, RunStatus.RUNNING)
        next_sequence = self._append_events(
            run_id,
            [
                RunEvent(
                    run_id=run_id,
                    sequence=1,
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
                    sequence=2,
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
            start_sequence=1,
        )
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
        self._repository.set_run_status(run_id, RunStatus.COMPLETED)
        return RunCreated(run_id=run_id, status=RunStatus.COMPLETED)

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
