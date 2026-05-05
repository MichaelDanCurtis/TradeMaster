from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date, datetime, timezone
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
from tradingagents.ui.observability import LangfuseClientFactory, ObservabilityService
from tradingagents.ui.providers import ProviderCatalog, get_provider_catalog
from tradingagents.ui.portfolio_data.base import (
    PortfolioAccount,
    PortfolioHolding,
    PortfolioProvider,
    PortfolioTransaction,
)
from tradingagents.ui.portfolio_data.plaid import (
    HttpClient as PlaidHttpClient,
    PlaidPortfolioProvider,
)
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import RealRunRunner, TradingRunService
from tradingagents.ui.secrets import EnvSecretStore, MacKeychainSecretStore, SecretNotFoundError
from tradingagents.ui.snapshots import (
    create_encrypted_snapshot_bundle,
    create_snapshot_manifest,
    verify_encrypted_snapshot_bundle,
)


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


class PrivateOfficeEdgeRequest(BaseModel):
    source_entity_id: str
    target_entity_id: str
    relationship: str
    payload: dict[str, object] = Field(default_factory=dict)


class GoalRequest(BaseModel):
    goal_id: str
    label: str
    target_amount: float | None = None
    target_date: str | None = None
    status: str = "draft"
    payload: dict[str, object] = Field(default_factory=dict)


class AssetRequest(BaseModel):
    asset_id: str
    label: str
    asset_type: str
    jurisdiction: str | None = None
    status: str = "draft"
    payload: dict[str, object] = Field(default_factory=dict)


class PortfolioMandateRequest(BaseModel):
    name: str
    control_mode: str
    account_ref: str
    funding_limit: float = Field(gt=0)
    max_position_percent: float = Field(gt=0)
    max_drawdown_percent: float = Field(ge=0)
    daily_turnover_limit_percent: float = Field(gt=0)
    paper_mode_required: bool
    kill_switch_enabled: bool
    status: str = "draft"
    payload: dict[str, object] = Field(default_factory=dict)


class SnapshotRequest(BaseModel):
    encryption_mode: str = "none"
    offsite_target: str | None = None
    backup_key_ref: str | None = None


class SnapshotVerifyRequest(BaseModel):
    backup_key_ref: str


class BarsResponse(BaseModel):
    bars: list[MarketDataBar]


class QuoteResponse(BaseModel):
    quote: MarketDataQuote


class AccountsResponse(BaseModel):
    accounts: list[PortfolioAccount]


class HoldingsResponse(BaseModel):
    holdings: list[PortfolioHolding]


class TransactionsResponse(BaseModel):
    transactions: list[PortfolioTransaction]


class RunTraceResponse(BaseModel):
    trace_id: str
    run_id: str
    provider: str
    status: str
    external_trace_id: str | None = None
    metadata: dict[str, object]
    cost: dict[str, object]
    created_at: datetime
    updated_at: datetime


def create_app(
    database_url: str | None = None,
    *,
    real_runner: RealRunRunner | None = None,
    market_data_providers: Mapping[str, MarketDataProvider] | None = None,
    market_data_http_client: HttpClient | None = None,
    portfolio_providers: Mapping[str, PortfolioProvider] | None = None,
    portfolio_http_client: PlaidHttpClient | None = None,
    langfuse_client_factory: LangfuseClientFactory | None = None,
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
    resolved_portfolio_providers = dict(portfolio_providers or {})

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

    def observability_service(
        repo: UiRepository = Depends(repository),
    ) -> ObservabilityService:
        return ObservabilityService(
            repo,
            secret_store_factory=_secret_store_for_ref,
            langfuse_client_factory=langfuse_client_factory,
        )

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

    @app.post("/api/provider-configs/{provider_id}/health-check")
    def check_provider_health(
        provider_id: str,
        repo: UiRepository = Depends(repository),
    ):
        try:
            config = repo.get_provider_config(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Provider not found") from exc

        secret_health = _describe_secret_ref(config.secret_ref)
        status = "available" if config.enabled and secret_health["available"] else "needs_key"
        health = {
            "secret": secret_health,
            "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        updated = repo.upsert_provider_config(
            provider_id=provider_id,
            health=health,
            status=status,
        )
        repo.append_private_office_event(
            event_type="provider.health_checked",
            summary=f"Checked {provider_id} secret health.",
            actor="Provider Registry",
            entity_id=f"provider_{provider_id.replace('-', '_')}",
            payload={
                "provider_id": provider_id,
                "secret_backend": secret_health["backend"],
                "secret_available": secret_health["available"],
                "status": status,
            },
        )
        return updated

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

    @app.get("/api/private-office/edges")
    def list_private_office_edges(
        source_entity_id: str | None = None,
        target_entity_id: str | None = None,
        repo: UiRepository = Depends(repository),
    ):
        return {
            "edges": repo.list_private_office_edges(
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
            )
        }

    @app.post("/api/private-office/edges")
    def link_private_office_entities(
        request: PrivateOfficeEdgeRequest,
        repo: UiRepository = Depends(repository),
    ):
        try:
            return repo.link_private_office_entities(
                source_entity_id=request.source_entity_id,
                target_entity_id=request.target_entity_id,
                relationship=request.relationship,
                payload=request.payload,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Private-office entity not found") from exc

    @app.get("/api/goals")
    def list_goals(repo: UiRepository = Depends(repository)):
        return {"goals": repo.list_private_office_entities(entity_type="goal")}

    @app.post("/api/goals")
    def upsert_goal(
        request: GoalRequest,
        repo: UiRepository = Depends(repository),
    ):
        payload = {
            **request.payload,
            "target_amount": request.target_amount,
            "target_date": request.target_date,
            "status": request.status,
        }
        record = repo.upsert_private_office_entity(
            entity_id=request.goal_id,
            entity_type="goal",
            label=request.label,
            payload=payload,
        )
        repo.append_private_office_event(
            event_type="goal.dossier_upserted",
            summary=f"Updated goal dossier: {request.label}.",
            actor="local-user",
            entity_id=request.goal_id,
            payload={"status": request.status},
        )
        return record

    @app.get("/api/assets")
    def list_assets(repo: UiRepository = Depends(repository)):
        return {"assets": repo.list_private_office_entities(entity_type="asset")}

    @app.post("/api/assets")
    def upsert_asset(
        request: AssetRequest,
        repo: UiRepository = Depends(repository),
    ):
        payload = {
            **request.payload,
            "asset_type": request.asset_type,
            "jurisdiction": request.jurisdiction,
            "status": request.status,
        }
        record = repo.upsert_private_office_entity(
            entity_id=request.asset_id,
            entity_type="asset",
            label=request.label,
            payload=payload,
        )
        repo.append_private_office_event(
            event_type="asset.dossier_upserted",
            summary=f"Updated asset dossier: {request.label}.",
            actor="local-user",
            entity_id=request.asset_id,
            payload={"asset_type": request.asset_type, "status": request.status},
        )
        return record

    @app.get("/api/portfolio-mandates")
    def list_portfolio_mandates(
        control_mode: str | None = None,
        repo: UiRepository = Depends(repository),
    ):
        return {
            "mandates": repo.list_portfolio_mandates(control_mode=control_mode)
        }

    @app.post("/api/portfolio-mandates")
    def create_portfolio_mandate(
        request: PortfolioMandateRequest,
        repo: UiRepository = Depends(repository),
    ):
        try:
            mandate = repo.create_portfolio_mandate(
                name=request.name,
                control_mode=request.control_mode,
                account_ref=request.account_ref,
                funding_limit=request.funding_limit,
                max_position_percent=request.max_position_percent,
                max_drawdown_percent=request.max_drawdown_percent,
                daily_turnover_limit_percent=request.daily_turnover_limit_percent,
                paper_mode_required=request.paper_mode_required,
                kill_switch_enabled=request.kill_switch_enabled,
                status=request.status,
                payload=request.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        repo.append_private_office_event(
            event_type="portfolio_mandate.created",
            summary=f"Created portfolio mandate: {request.name}.",
            actor="local-user",
            entity_id=mandate.mandate_id,
            payload={
                "control_mode": request.control_mode,
                "account_ref": request.account_ref,
                "status": request.status,
            },
        )
        return mandate

    @app.post("/api/snapshots")
    def create_snapshot(
        request: SnapshotRequest,
        repo: UiRepository = Depends(repository),
    ):
        try:
            database_path = _sqlite_database_path(resolved_database_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if request.backup_key_ref is None:
            manifest = create_snapshot_manifest(
                database_path=database_path,
                encryption_mode=request.encryption_mode,
                offsite_target=request.offsite_target,
            )
        else:
            try:
                backup_key = _secret_store_for_ref(request.backup_key_ref).get_secret(
                    request.backup_key_ref
                )
            except SecretNotFoundError as exc:
                raise HTTPException(status_code=403, detail="Backup key is not available") from exc
            manifest = create_encrypted_snapshot_bundle(
                database_path=database_path,
                output_dir=database_path.parent / "backups",
                key_material=backup_key,
                offsite_target=request.offsite_target,
            )
        record = repo.store_snapshot_manifest(
            snapshot_id=manifest["snapshot_id"],
            storage_profile=manifest["storage_profile"],
            encryption_mode=manifest["encryption_mode"],
            offsite_target=manifest["offsite_target"],
            manifest=manifest,
        )
        repo.append_private_office_event(
            event_type="snapshot.created",
            summary="Created encrypted backup snapshot."
            if manifest["encrypted"]
            else "Created local backup snapshot manifest.",
            actor="Backup",
            entity_id=record.snapshot_id,
            payload={
                "encrypted": manifest["encrypted"],
                "offsite_target": manifest["offsite_target"],
                "artifact_path": manifest.get("backup_artifact", {}).get("path"),
            },
        )
        return record

    @app.post("/api/snapshots/{snapshot_id}/verify")
    def verify_snapshot(
        snapshot_id: str,
        request: SnapshotVerifyRequest,
        repo: UiRepository = Depends(repository),
    ):
        try:
            record = repo.get_snapshot_manifest(snapshot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Snapshot not found") from exc
        artifact = record.manifest.get("backup_artifact")
        if not isinstance(artifact, dict) or artifact.get("path") is None:
            raise HTTPException(status_code=400, detail="Snapshot has no encrypted backup artifact")
        try:
            backup_key = _secret_store_for_ref(request.backup_key_ref).get_secret(
                request.backup_key_ref
            )
        except SecretNotFoundError as exc:
            raise HTTPException(status_code=403, detail="Backup key is not available") from exc
        verification = verify_encrypted_snapshot_bundle(
            artifact_path=Path(str(artifact["path"])),
            key_material=backup_key,
        )
        repo.append_private_office_event(
            event_type="snapshot.verified",
            summary="Verified encrypted backup snapshot."
            if verification["valid"]
            else "Encrypted backup snapshot verification failed.",
            actor="Backup",
            entity_id=snapshot_id,
            payload={
                "valid": verification["valid"],
                "artifact_path": artifact["path"],
            },
        )
        return verification

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
            bars = provider.historical_bars(
                symbol=symbol,
                start=start,
                end=end,
                timeframe=timeframe,
                limit=limit,
                feed=resolved_feed,
            )
            repo.store_market_data_snapshot(
                provider_id=provider_id,
                symbol=symbol,
                snapshot_kind="bars",
                feed=resolved_feed,
                timeframe=timeframe,
                payload={
                    "bars": [bar.model_dump(mode="json") for bar in bars],
                    "request": {
                        "end": end.isoformat(),
                        "limit": limit,
                        "start": start.isoformat(),
                    },
                },
            )
            return BarsResponse(bars=bars)
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
            resolved_feed = feed or _configured_feed(provider_config)
            quote = provider.latest_quote(
                symbol,
                feed=resolved_feed,
            )
            repo.store_market_data_snapshot(
                provider_id=provider_id,
                symbol=symbol,
                snapshot_kind="quote",
                feed=resolved_feed,
                payload={"quote": quote.model_dump(mode="json")},
            )
            return QuoteResponse(quote=quote)
        except SecretNotFoundError as exc:
            raise HTTPException(
                status_code=403,
                detail="Market data secret is not available",
            ) from exc

    @app.get("/api/portfolio-data/{provider_id}/accounts", response_model=AccountsResponse)
    def get_portfolio_accounts(
        provider_id: str,
        repo: UiRepository = Depends(repository),
    ) -> AccountsResponse:
        provider = _resolve_portfolio_provider(
            provider_id,
            resolved_portfolio_providers,
            repo,
            portfolio_http_client,
        )
        try:
            return AccountsResponse(accounts=provider.accounts())
        except SecretNotFoundError as exc:
            raise HTTPException(
                status_code=403,
                detail="Portfolio data secret is not available",
            ) from exc

    @app.get("/api/portfolio-data/{provider_id}/holdings", response_model=HoldingsResponse)
    def get_portfolio_holdings(
        provider_id: str,
        repo: UiRepository = Depends(repository),
    ) -> HoldingsResponse:
        provider = _resolve_portfolio_provider(
            provider_id,
            resolved_portfolio_providers,
            repo,
            portfolio_http_client,
        )
        try:
            return HoldingsResponse(holdings=provider.holdings())
        except SecretNotFoundError as exc:
            raise HTTPException(
                status_code=403,
                detail="Portfolio data secret is not available",
            ) from exc

    @app.get(
        "/api/portfolio-data/{provider_id}/transactions",
        response_model=TransactionsResponse,
    )
    def get_portfolio_transactions(
        provider_id: str,
        start_date: date,
        end_date: date,
        repo: UiRepository = Depends(repository),
    ) -> TransactionsResponse:
        provider = _resolve_portfolio_provider(
            provider_id,
            resolved_portfolio_providers,
            repo,
            portfolio_http_client,
        )
        try:
            return TransactionsResponse(
                transactions=provider.transactions(
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        except SecretNotFoundError as exc:
            raise HTTPException(
                status_code=403,
                detail="Portfolio data secret is not available",
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

    @app.get("/api/runs/{run_id}/trace", response_model=RunTraceResponse)
    def get_run_trace(
        run_id: str,
        repo: UiRepository = Depends(repository),
    ) -> RunTraceResponse:
        try:
            trace = repo.get_observability_trace(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run trace not found") from exc
        return _run_trace_response(trace)

    @app.post("/api/runs/{run_id}/trace/export", response_model=RunTraceResponse)
    def export_run_trace(
        run_id: str,
        service: ObservabilityService = Depends(observability_service),
    ) -> RunTraceResponse:
        try:
            trace = service.export_run_trace(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run trace not found") from exc
        except SecretNotFoundError as exc:
            raise HTTPException(
                status_code=403,
                detail="LangFuse observability secret is not available",
            ) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return _run_trace_response(trace)

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


def _run_trace_response(trace) -> RunTraceResponse:
    return RunTraceResponse(
        trace_id=trace.trace_id,
        run_id=trace.run_id,
        provider=trace.provider,
        status=trace.status,
        external_trace_id=trace.external_trace_id,
        metadata=trace.metadata_payload,
        cost=trace.cost,
        created_at=trace.created_at,
        updated_at=trace.updated_at,
    )


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


def _describe_secret_ref(secret_ref: str | None) -> dict[str, object]:
    if secret_ref is None:
        return {"backend": "none", "available": False}
    return _secret_store_for_ref(secret_ref).describe_secret(secret_ref)


def _resolve_portfolio_provider(
    provider_id: str,
    providers: Mapping[str, PortfolioProvider],
    repo: UiRepository,
    portfolio_http_client: PlaidHttpClient | None,
) -> PortfolioProvider:
    provider = providers.get(provider_id)
    if provider is not None:
        return provider
    if provider_id != "plaid-investments":
        raise HTTPException(status_code=404, detail="Portfolio provider not configured")
    try:
        config = repo.get_provider_config(provider_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Portfolio provider not configured") from exc
    if not config.enabled or config.secret_ref is None:
        raise HTTPException(
            status_code=403,
            detail="Plaid portfolio data is disabled or missing a secret_ref",
        )
    return PlaidPortfolioProvider(
        secret_store=_secret_store_for_ref(config.secret_ref),
        secret_ref=config.secret_ref,
        http_client=portfolio_http_client,
    )
