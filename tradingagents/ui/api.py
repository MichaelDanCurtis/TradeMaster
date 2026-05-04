from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.brokers.service import BrokerService
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig, RunCreated, RunEvent
from tradingagents.ui.market_data.alpaca import AlpacaMarketDataProvider, HttpClient
from tradingagents.ui.market_data.base import (
    BarTimeframe,
    MarketDataBar,
    MarketDataProvider,
    MarketDataQuote,
)
from tradingagents.ui.providers import ProviderCatalog, get_provider_catalog
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import RealRunRunner, TradingRunService
from tradingagents.ui.secrets import EnvSecretStore, MacKeychainSecretStore, SecretNotFoundError
from tradingagents.ui.snapshots import create_snapshot_manifest


class TradePreviewRequest(BaseModel):
    run_id: str
    symbol: str
    side: Literal["buy", "sell"]
    notional: float = Field(gt=0)


class ApprovalRequest(BaseModel):
    actor: str = "local-user"


class ProviderConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    secret_ref: str | None = None
    config: dict[str, object] | None = None
    health: dict[str, object] | None = None
    status: str | None = None


class PrivateOfficeEventRequest(BaseModel):
    event_type: str
    summary: str
    actor: str
    entity_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class SnapshotRequest(BaseModel):
    encryption_mode: str = "none"
    offsite_target: str | None = None


class BarsResponse(BaseModel):
    bars: list[MarketDataBar]


class QuoteResponse(BaseModel):
    quote: MarketDataQuote


def create_app(
    database_url: str | None = None,
    *,
    real_runner: RealRunRunner | None = None,
    market_data_providers: Mapping[str, MarketDataProvider] | None = None,
    market_data_http_client: HttpClient | None = None,
) -> FastAPI:
    resolved_database_url = (
        database_url
        or os.environ.get("TRADINGAGENTS_UI_DATABASE_URL")
        or "sqlite:///./.tradingagents-ui.db"
    )
    engine, session_factory = create_session_factory(resolved_database_url)
    init_db(engine)
    resolved_real_runner = real_runner
    if resolved_real_runner is None and os.environ.get("TRADEMASTER_ENABLE_REAL_RUNS") == "1":
        from tradingagents.ui.graph_runner import TradingAgentsGraphRunner

        resolved_real_runner = TradingAgentsGraphRunner()
    resolved_market_data_providers = dict(market_data_providers or {})

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
        return TradingRunService(repository, real_runner=resolved_real_runner)

    def broker_service(repo: UiRepository = Depends(repository)) -> BrokerService:
        return BrokerService(repo, FakePaperBroker())

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "tradingagents-ui"}

    @app.get("/api/providers", response_model=ProviderCatalog)
    def list_providers() -> ProviderCatalog:
        return get_provider_catalog()

    @app.get("/api/provider-configs")
    def list_provider_configs(repo: UiRepository = Depends(repository)):
        return {"providers": repo.list_provider_configs()}

    @app.post("/api/provider-configs/{provider_id}")
    def update_provider_config(
        provider_id: str,
        request: ProviderConfigUpdateRequest,
        repo: UiRepository = Depends(repository),
    ):
        try:
            return repo.upsert_provider_config(
                provider_id=provider_id,
                enabled=request.enabled,
                secret_ref=request.secret_ref,
                config=request.config,
                health=request.health,
                status=request.status,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Provider not found") from exc

    @app.post("/api/private-office/events")
    def append_private_office_event(
        request: PrivateOfficeEventRequest,
        repo: UiRepository = Depends(repository),
    ):
        return repo.append_private_office_event(
            event_type=request.event_type,
            summary=request.summary,
            actor=request.actor,
            entity_id=request.entity_id,
            payload=request.payload,
        )

    @app.post("/api/snapshots")
    def create_snapshot(
        request: SnapshotRequest,
        repo: UiRepository = Depends(repository),
    ):
        try:
            database_path = _sqlite_database_path(resolved_database_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        manifest = create_snapshot_manifest(
            database_path=database_path,
            encryption_mode=request.encryption_mode,
            offsite_target=request.offsite_target,
        )
        return repo.store_snapshot_manifest(
            snapshot_id=manifest["snapshot_id"],
            storage_profile=manifest["storage_profile"],
            encryption_mode=manifest["encryption_mode"],
            offsite_target=manifest["offsite_target"],
            manifest=manifest,
        )

    @app.get("/api/market-data/{provider_id}/bars", response_model=BarsResponse)
    def get_market_data_bars(
        provider_id: str,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: BarTimeframe,
        limit: int | None = None,
        feed: str | None = None,
        repo: UiRepository = Depends(repository),
    ) -> BarsResponse:
        provider, provider_config = _resolve_market_data_provider(
            provider_id,
            resolved_market_data_providers,
            repo,
            market_data_http_client,
        )
        resolved_feed = feed or _configured_feed(provider_config)
        try:
            return BarsResponse(
                bars=provider.historical_bars(
                    symbol=symbol,
                    start=start,
                    end=end,
                    timeframe=timeframe,
                    limit=limit,
                    feed=resolved_feed,
                )
            )
        except SecretNotFoundError as exc:
            raise HTTPException(
                status_code=403,
                detail="Market data secret is not available",
            ) from exc

    @app.get("/api/market-data/{provider_id}/quote", response_model=QuoteResponse)
    def get_market_data_quote(
        provider_id: str,
        symbol: str,
        feed: str | None = None,
        repo: UiRepository = Depends(repository),
    ) -> QuoteResponse:
        provider, provider_config = _resolve_market_data_provider(
            provider_id,
            resolved_market_data_providers,
            repo,
            market_data_http_client,
        )
        try:
            return QuoteResponse(
                quote=provider.latest_quote(
                    symbol,
                    feed=feed or _configured_feed(provider_config),
                )
            )
        except SecretNotFoundError as exc:
            raise HTTPException(
                status_code=403,
                detail="Market data secret is not available",
            ) from exc

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


def _sqlite_database_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("snapshot endpoint currently supports sqlite:/// database URLs")
    return Path(unquote(database_url.removeprefix(prefix)))


def _resolve_market_data_provider(
    provider_id: str,
    providers: Mapping[str, MarketDataProvider],
    repo: UiRepository,
    market_data_http_client: HttpClient | None,
) -> tuple[MarketDataProvider, dict[str, object]]:
    provider = providers.get(provider_id)
    if provider is not None:
        return provider, {}
    if provider_id != "alpaca-market-data":
        raise HTTPException(status_code=404, detail="Market data provider not configured")
    try:
        config = repo.get_provider_config(provider_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Market data provider not configured") from exc
    if not config.enabled or config.secret_ref is None:
        raise HTTPException(
            status_code=403,
            detail="Alpaca market data is disabled or missing a secret_ref",
        )
    return (
        AlpacaMarketDataProvider(
            secret_store=_secret_store_for_ref(config.secret_ref),
            secret_ref=config.secret_ref,
            http_client=market_data_http_client,
        ),
        config.config,
    )


def _configured_feed(config: Mapping[str, object]) -> str | None:
    feed = config.get("feed")
    if feed is None:
        return None
    return str(feed)


def _secret_store_for_ref(secret_ref: str):
    if secret_ref.startswith("env:"):
        return EnvSecretStore()
    if secret_ref.startswith("keychain:"):
        return MacKeychainSecretStore()
    raise HTTPException(status_code=400, detail="Unsupported secret_ref backend")
