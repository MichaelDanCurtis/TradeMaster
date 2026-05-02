from __future__ import annotations

import os
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.brokers.service import BrokerService
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig, RunCreated, RunEvent
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import TradingRunService


class TradePreviewRequest(BaseModel):
    run_id: str
    symbol: str
    side: Literal["buy", "sell"]
    notional: float = Field(gt=0)


class ApprovalRequest(BaseModel):
    actor: str = "local-user"


def create_app(database_url: str | None = None) -> FastAPI:
    resolved_database_url = (
        database_url
        or os.environ.get("TRADINGAGENTS_UI_DATABASE_URL")
        or "sqlite:///./.tradingagents-ui.db"
    )
    engine, session_factory = create_session_factory(resolved_database_url)
    init_db(engine)

    app = FastAPI(title="TradingAgents UI API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def repository() -> UiRepository:
        return UiRepository(session_factory)

    def run_service(
        repository: UiRepository = Depends(repository),
    ) -> TradingRunService:
        return TradingRunService(repository)

    def broker_service(repo: UiRepository = Depends(repository)) -> BrokerService:
        return BrokerService(repo, FakePaperBroker())

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "tradingagents-ui"}

    @app.post("/api/runs", response_model=RunCreated)
    def create_run(
        config: RunConfig,
        service: TradingRunService = Depends(run_service),
    ) -> RunCreated:
        return service.start_run(config)

    @app.get("/api/runs/{run_id}/events", response_model=list[RunEvent])
    def list_events(
        run_id: str,
        service: TradingRunService = Depends(run_service),
    ) -> list[RunEvent]:
        try:
            return service.list_events(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

    @app.get("/api/runs/{run_id}/stream")
    def stream_events(
        run_id: str,
        service: TradingRunService = Depends(run_service),
    ) -> StreamingResponse:
        try:
            service.list_events(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

        return StreamingResponse(
            service.stream_sse(run_id),
            media_type="text/event-stream",
        )

    @app.post("/api/trades/preview")
    def preview_trade(
        request: TradePreviewRequest,
        service: BrokerService = Depends(broker_service),
    ):
        try:
            return service.preview_order(
                run_id=request.run_id,
                symbol=request.symbol,
                side=request.side,
                notional=request.notional,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trade or run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/trades/{intent_id}/approve")
    def approve_trade(
        intent_id: str,
        request: ApprovalRequest,
        service: BrokerService = Depends(broker_service),
    ) -> dict[str, str]:
        try:
            service.approve_order(intent_id, actor=request.actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trade or run not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"intent_id": intent_id, "status": "approved"}

    @app.post("/api/trades/{intent_id}/submit")
    def submit_trade(
        intent_id: str,
        service: BrokerService = Depends(broker_service),
    ):
        try:
            return service.submit_approved_order(intent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trade or run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    return app
