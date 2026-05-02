from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timezone
from typing import Any

from tradingagents.ui.events import RunConfig, RunCreated, RunEvent, RunStatus
from tradingagents.ui.repository import UiRepository


class TradingRunService:
    def __init__(self, repository: UiRepository) -> None:
        self._repository = repository

    def start_run(self, config: RunConfig) -> RunCreated:
        run = self._repository.create_run(config)
        self._append_fake_events(run.run_id, config)
        return RunCreated(run_id=run.run_id, status=RunStatus.COMPLETED)

    def list_events(self, run_id: str) -> list[RunEvent]:
        return self._repository.list_events(run_id)

    def stream_sse(self, run_id: str) -> Iterator[str]:
        for event in self.list_events(run_id):
            data = json.dumps(self._serialize_event(event), separators=(",", ":"))
            yield f"event: {event.type}\ndata: {data}\n\n"

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
