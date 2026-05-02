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
        fake_events: list[dict[str, Any]] = [
            {
                "type": "run.created",
                "node": None,
                "message": f"Created simulated run for {config.ticker}.",
                "payload": {"ticker": config.ticker},
            },
            {
                "type": "run.started",
                "node": None,
                "message": "Started simulated TradingAgents run.",
                "payload": {"trade_date": config.trade_date},
            },
            {
                "type": "agent.started",
                "node": "Market Analyst",
                "message": "Market Analyst started.",
                "payload": {"analyst": "market"},
            },
            {
                "type": "tool.called",
                "node": "Market Analyst",
                "message": "Fetched simulated market context.",
                "payload": {"tool": "fake_market_snapshot"},
            },
            {
                "type": "report.updated",
                "node": "Market Analyst",
                "message": "Updated simulated market report.",
                "payload": {"section": "market"},
            },
            {
                "type": "agent.started",
                "node": "Portfolio Manager",
                "message": "Portfolio Manager started.",
                "payload": {"agent": "portfolio_manager"},
            },
            {
                "type": "decision.created",
                "node": "Portfolio Manager",
                "message": "Created simulated decision.",
                "payload": {"rating": "Overweight", "action": "Buy"},
            },
        ]
        if config.broker_mode == "paper":
            fake_events.append(
                {
                    "type": "trade.previewed",
                    "node": "Broker",
                    "message": "Previewed simulated paper trade.",
                    "payload": {"symbol": config.ticker, "side": "buy"},
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
