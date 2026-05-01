from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig, RunCreated, RunEvent
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import TradingRunService


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

    return app
