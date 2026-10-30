from __future__ import annotations

from tradingagents.ui.lifecycle import on_lifecycle, application_lifespan

import asyncio
import os
import threading
import time
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Load .env at import time so uvicorn-style entry points (which skip main.py
# and call create_app directly) still see credentials like FINNHUB_API_KEY,
# ALPACA_API_KEY, etc.
load_dotenv()

from tradingagents.dataflows.finnhub_utils import (
    FinnhubError,
    fetch_company_news,
    fetch_general_news,
    normalize_news_item,
)
from tradingagents.ui.quick_scan import run_quick_scan
from tradingagents.ui.research_explorer import ExplorerResponse, explore_market
from tradingagents.ui.brokers.alpaca import AlpacaPaperBroker
from tradingagents.ui.brokers.base import BrokerAdapter
from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.brokers.service import BrokerService
from tradingagents.ui.agent_packs.importer import import_agent_pack
from tradingagents.ui.constraints import (
    ConstraintContext,
    PortfolioConstraintPolicy,
    SymbolicConstraintEngine,
)
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig, RunCreated, RunEvent, RunSummary
from tradingagents.algorithms import list_by_category as _list_algorithms_by_category
from tradingagents.ui.execution_algorithms import ExecutionAlgorithmPlan, preview_execution_algorithm
from tradingagents.ui.llm_runner import LlmResearchRunner, _provider_requires_secret
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
from tradingagents.ui.portfolio_data.alpaca import AlpacaPortfolioProvider
from tradingagents.ui.portfolio_data.plaid import (
    HttpClient as PlaidHttpClient,
    PlaidPortfolioProvider,
)
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.models import (
    AgentOperationRecord,
    AgentTriggerRecord,
    ApprovalLedgerRecord,
    ExecutionProgramEventRecord,
    ExecutionProgramRecord,
    FundingAllocationReviewRecord,
    PortfolioReviewRecord,
    ReportScheduleRecord,
    SnapshotManifestRecord,
    TradeThesisRecord,
)
from tradingagents.ui.room_policy import enforce_room_tool, evaluate_room_tool, list_room_policies
from tradingagents.ui.runner import RealRunRunner, TradingRunService
from tradingagents.ui.secrets import EnvSecretStore, MacKeychainSecretStore, SecretNotFoundError
from tradingagents.ui.snapshots import (
    create_encrypted_snapshot_bundle,
    create_snapshot_manifest,
    verify_encrypted_snapshot_bundle,
)
from tradingagents.ui.trigger_harness import evaluate_agent_triggers
from tradingagents.ui.watchers.conditions import CONDITION_TYPES as _WATCHER_CONDITION_TYPES
from tradingagents.ui.watchers.firing_loop import (
    POLL_INTERVAL_SECONDS as _WATCHER_POLL_INTERVAL_SECONDS,
    check_watcher_once as _check_watcher_once,
    start_firing_loop as _start_watcher_firing_loop,
)


class TradeRiskControls(BaseModel):
    """Optional protective stop / take-profit envelope.

    Sent on the preview body so the Risk Manager's advisory figures
    can be promoted to a real Alpaca bracket / OTO order when the
    operator picks ``broker_protective``. ``advisory_only`` keeps the
    legacy behaviour: figures stored on the intent for audit, broker
    sees only a market order.
    """

    stop_loss: float | None = None
    take_profit: float | None = None
    mode: Literal["advisory_only", "broker_protective"] = "advisory_only"


class TradePreviewRequest(BaseModel):
    run_id: str | None = None
    symbol: str
    side: Literal["buy", "sell"]
    notional: float = Field(gt=0)
    room_id: str = "market"
    risk_controls: TradeRiskControls | None = None


class ExecutionAlgorithmPreviewRequest(BaseModel):
    # `algorithm` was originally a 3-name Literal. It is now `str` to admit the
    # 27-algorithm catalogue registered under `tradingagents.algorithms`.
    # The registry validates the name at preview time and the endpoint returns
    # HTTP 400 on unknown names via the existing ValueError handler below.
    algorithm: str
    symbol: str
    side: Literal["buy", "sell"]
    notional: float = Field(gt=0)
    reference_price: float = Field(gt=0)
    room_id: str = "market"
    # Optional algorithm-specific overrides (e.g., window_minutes for TWAP,
    # win_probability for kelly_fraction). Each algorithm exposes its own
    # Params model with sane defaults; the registry validates unknown keys
    # by ignoring them rather than rejecting the call.
    parameters: dict[str, Any] | None = None


class ApprovalRequest(BaseModel):
    actor: str = Field(default="local-user", min_length=1, max_length=200)
    expected_order_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class RoomToolPolicyRequest(BaseModel):
    room_id: str
    tool_grant: str


class ApprovalLedgerRequest(BaseModel):
    room_id: str
    source: str
    entity_type: str
    entity_id: str
    action: Literal["accept", "reject", "revise", "defer", "escalate"]
    actor: str
    summary: str
    payload: dict[str, object] = Field(default_factory=dict)


class AgentTriggerRequest(BaseModel):
    name: str
    room_id: str
    trigger_type: Literal[
        "time",
        "price",
        "volume",
        "sentiment_flip",
        "report_event",
        "risk_threshold",
        "compliance_flag",
    ]
    target_agent: str
    symbol: str | None = None
    condition: dict[str, object] = Field(default_factory=dict)
    workflow_id: str | None = None
    enabled: bool = True
    payload: dict[str, object] = Field(default_factory=dict)


class AgentTriggerEvaluationRequest(BaseModel):
    event: dict[str, object] = Field(default_factory=dict)
    room_id: str | None = None
    symbol: str | None = None


class TradeThesisRequest(BaseModel):
    symbol: str
    source_report_id: str | None = None
    source_room: str = "research"
    target_room: str = "market"
    direction: Literal["long", "short", "neutral", "hedge", "exit"]
    horizon: str
    conviction: float = Field(ge=0, le=1)
    thesis: str
    catalysts: list[str] = Field(default_factory=list)
    invalidation: list[str] = Field(default_factory=list)
    risk_notes: str | None = None
    status: Literal[
        "proposed",
        "accepted",
        "rejected",
        "revised",
        "deferred",
        "sent_to_broker",
    ] = "proposed"
    payload: dict[str, object] = Field(default_factory=dict)


class PortfolioReviewRequest(BaseModel):
    symbol: str
    room_id: str = "portfolio"
    status: str = "draft"
    goals: str | None = None
    horizon: str | None = None
    risk_posture: str | None = None
    sector_focus: str | None = None
    constraints: str | None = None
    liquidity_needs: str | None = None
    thesis: dict[str, object] = Field(default_factory=dict)
    missing_provider_facts: list[str] = Field(default_factory=list)
    payload: dict[str, object] = Field(default_factory=dict)


class FundingAllocationReviewRequest(BaseModel):
    symbol: str
    source_thesis_id: str | None = None
    execution_program_id: str | None = None
    status: str = "draft"
    notional: float | None = Field(default=None, gt=0)
    tracks: list[dict[str, object]] = Field(default_factory=list)
    missing_provider_facts: list[str] = Field(default_factory=list)
    approval_next_steps: list[str] = Field(default_factory=list)
    payload: dict[str, object] = Field(default_factory=dict)


class ExecutionProgramRequest(BaseModel):
    symbol: str
    source_thesis_id: str | None = None
    algorithm: str
    state: str = "preview_ready"
    mode: str = "paper"
    approval_status: str = "required"
    live_submission_enabled: bool = False
    trigger_points: list[dict[str, object]] = Field(default_factory=list)
    circuit_breakers: list[dict[str, object]] = Field(default_factory=list)
    missing_provider_facts: list[str] = Field(default_factory=list)
    payload: dict[str, object] = Field(default_factory=dict)


class ExecutionProgramEventRequest(BaseModel):
    event_type: str
    summary: str
    payload: dict[str, object] = Field(default_factory=dict)


class ProviderConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    secret_ref: str | None = None
    config: dict[str, object] | None = None
    health: dict[str, object] | None = None
    status: str | None = None


class UserProviderCreateRequest(BaseModel):
    name: str
    kind: Literal["openai-compatible", "anthropic-compatible"]
    base_url: str
    model: str
    api_key_env: str | None = None
    role_models: dict[str, object] | None = None


class ProviderRoleAssignmentRequest(BaseModel):
    provider_id: str


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


class AgentWorkflowRequest(BaseModel):
    name: str
    agent_class: Literal["research", "execution"]
    graph_runtime: Literal["langgraph", "langchain", "manual"]
    status: str = "draft"
    nodes: list[dict[str, object]]
    edges: list[dict[str, object]] = Field(default_factory=list)
    required_provider_roles: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, object] = Field(default_factory=dict)


class AgentOperationRequest(BaseModel):
    agent_id: str
    agent_name: str
    room_id: str
    symbol: str
    operation_type: str
    authority: str
    source_workflow_id: str | None = None
    linked_run_id: str | None = None
    linked_execution_program_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class AgentOperationCompleteRequest(BaseModel):
    linked_run_id: str | None = None
    linked_execution_program_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class AgentPackImportRequest(BaseModel):
    pack_id: str
    source_path: str
    source_url: str | None = None
    source_commit: str | None = None


class AgentPackImportResponse(BaseModel):
    pack_id: str
    agent_count: int
    skill_count: int
    connector_count: int


class ReportScheduleRequest(BaseModel):
    name: str
    symbol: str
    cadence: Literal["market_open", "every_5_min", "hourly", "daily", "manual"]
    broker_mode: Literal["disabled", "paper", "live_preview"] = "disabled"
    execution_mode: Literal["real", "simulated"] = "real"
    enabled: bool = True
    payload: dict[str, object] = Field(default_factory=dict)


class ReportSchedulesResponse(BaseModel):
    schedules: list[ReportScheduleRecord]


class RunsResponse(BaseModel):
    """Catalog wrapper for ``GET /api/runs``.

    Wraps the run list so the endpoint matches the sibling-catalog
    shape used by every other GET listing (``{items}``/``{accounts}``/
    ``{schedules}``/etc.) instead of returning a bare array.
    """

    runs: list[RunSummary]


class SnapshotsResponse(BaseModel):
    """Catalog wrapper for ``GET /api/snapshots``."""

    items: list[SnapshotManifestRecord]


class ScanVerdict(BaseModel):
    """Latest completed-run verdict for one symbol (Morning Scan)."""

    symbol: str
    rating: str | None = None
    action: str | None = None
    thesis: str | None = None
    confidence: float | None = None
    run_id: str
    run_created_at: datetime


class ScanVerdictsResponse(BaseModel):
    """Catalog wrapper for ``GET /api/scans/verdicts``."""

    verdicts: list[ScanVerdict]


class ScanRequest(BaseModel):
    """Body for ``POST /api/scans`` — 1..10 symbols enforced by pydantic (422)."""

    symbols: list[str] = Field(min_length=1, max_length=10)


class ScanStartedEntry(BaseModel):
    symbol: str
    run_id: str


class ScanFailedEntry(BaseModel):
    symbol: str
    error: str


class ScanStartedResponse(BaseModel):
    started: list[ScanStartedEntry]
    failed: list[ScanFailedEntry] = Field(default_factory=list)


class QuickScanRequest(BaseModel):
    """Body for ``POST /api/quickscan`` — 1..12 symbols enforced by pydantic (422).

    The FRONTEND batches larger watchlists into <=12-symbol calls.
    """

    symbols: list[str] = Field(min_length=1, max_length=12)


class QuickScanResult(BaseModel):
    symbol: str
    stance: Literal["buy", "hold", "avoid"]
    conviction: int
    thesis: str
    catalyst: str
    risk: str
    model: str
    created_at: datetime


class QuickScanFailedEntry(BaseModel):
    symbol: str
    error: str


class QuickScanResponse(BaseModel):
    results: list[QuickScanResult]
    failed: list[QuickScanFailedEntry] = Field(default_factory=list)


class ReportScheduleTriggerResponse(BaseModel):
    schedule: ReportScheduleRecord
    run: RunCreated


class ReportScheduleBulkTriggerResponse(BaseModel):
    triggered_count: int
    results: list[ReportScheduleTriggerResponse]


class RuntimeStatusResponse(BaseModel):
    research_runner: dict[str, object]
    research_llm: dict[str, object]
    full_tradingagents_graph: dict[str, object]
    execution_policy: dict[str, object]
    broker: dict[str, object]
    developer_mode_enabled: bool = False


class RuntimeResearchRunnerRequest(BaseModel):
    mode: Literal["llm-ui-runner", "tradingagents-graph-runner"]


class RuntimeDeveloperModeRequest(BaseModel):
    enabled: bool


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


class DiscoverCandidate(BaseModel):
    symbol: str
    price: float | None = None
    change_pct: float | None = None
    volume: int | None = None
    source: str
    sources: list[str] = Field(default_factory=list)


class DiscoverCandidatesResponse(BaseModel):
    candidates: list[DiscoverCandidate]


class NewsItem(BaseModel):
    id: str
    published_at: str | None = None
    source: str = ""
    headline: str = ""
    summary: str = ""
    url: str = ""
    category: str = "company"
    related: str = ""
    image: str | None = None


class NewsResponse(BaseModel):
    symbol: str
    provider: str = "finnhub"
    since_hours: int
    items: list[NewsItem]


class OpenTrade(BaseModel):
    intent_id: str
    run_id: str
    symbol: str
    side: str
    notional: float
    order_type: str
    status: str
    created_at: str
    updated_at: str
    broker: str | None = None
    broker_environment: str | None = None
    broker_status: str | None = None
    broker_order_id: str | None = None
    execution_schedule_id: str | None = None


class OpenTradesResponse(BaseModel):
    items: list[OpenTrade]


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


WatcherConditionLiteral = Literal[
    "price_above",
    "price_below",
    "change_pct_above",
    "change_pct_below",
    "volume_above",
]


class Watcher(BaseModel):
    watcher_id: str
    name: str
    symbol: str
    condition_type: WatcherConditionLiteral
    threshold: float
    enabled: bool
    payload: dict[str, Any]
    linked_position_id: str | None
    linked_run_id: str | None
    last_fired_at: str | None
    fire_count: int
    created_at: str
    updated_at: str


class WatcherCatalog(BaseModel):
    watchers: list[Watcher]


class WatcherFire(BaseModel):
    fire_id: str
    watcher_id: str
    symbol: str
    fired_at: str
    observed_value: float
    threshold: float
    condition_type: str
    payload: dict[str, Any]


class WatcherFiresCatalog(BaseModel):
    fires: list[WatcherFire]


class CreateWatcherRequest(BaseModel):
    name: str
    symbol: str
    condition_type: WatcherConditionLiteral
    threshold: float
    enabled: bool = True
    cooldown_seconds: int = 300
    linked_position_id: str | None = None
    linked_run_id: str | None = None


class UpdateWatcherRequest(BaseModel):
    name: str | None = None
    threshold: float | None = None
    enabled: bool | None = None
    cooldown_seconds: int | None = None


def create_app(
    database_url: str | None = None,
    *,
    real_runner: RealRunRunner | None = None,
    market_data_providers: Mapping[str, MarketDataProvider] | None = None,
    market_data_http_client: HttpClient | None = None,
    broker_providers: Mapping[str, BrokerAdapter] | None = None,
    portfolio_providers: Mapping[str, PortfolioProvider] | None = None,
    portfolio_http_client: PlaidHttpClient | None = None,
    langfuse_client_factory: LangfuseClientFactory | None = None,
    llm_client_factory=None,
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

        resolved_real_runner = TradingAgentsGraphRunner(
            provider_config_resolver=lambda: _research_llm_provider_config(
                UiRepository(session_factory)
            ),
            secret_store_factory=_secret_store_for_ref,
        )
    resolved_market_data_providers = dict(market_data_providers or {})
    resolved_broker_providers = dict(broker_providers or {})
    resolved_portfolio_providers = dict(portfolio_providers or {})

    app = FastAPI(title="TradingAgents UI API", lifespan=application_lifespan)
    from tradingagents.ui.forecast_lab import create_forecast_router
    app.include_router(create_forecast_router(session_factory, lambda: _resolve_market_data_provider(
        "alpaca-market-data", resolved_market_data_providers, UiRepository(session_factory), market_data_http_client,
    ), app))
    from tradingagents.ui.research_desk import create_desk_router
    app.include_router(create_desk_router(session_factory, lambda: _resolve_broker_adapter(UiRepository(session_factory), resolved_broker_providers), app))
    from tradingagents.ui.portfolio_stress import create_stress_router
    app.include_router(create_stress_router(app.state.research_desk, lambda: _resolve_broker_adapter(UiRepository(session_factory), resolved_broker_providers)))
    from tradingagents.ui.forecast_tournament import create_tournament_router
    app.include_router(create_tournament_router(app.state.research_desk, app.state.forecast_lab, app))
    from tradingagents.ui.opportunity_lab import create_opportunity_router
    app.include_router(create_opportunity_router(app.state.research_desk, lambda: _resolve_market_data_provider(
        "alpaca-market-data", resolved_market_data_providers, UiRepository(session_factory), market_data_http_client,
    ), app))
    from tradingagents.research.api import create_research_router

    app.include_router(create_research_router(session_factory))
    from tradingagents.ui.explorer_briefs import create_brief_router
    app.include_router(create_brief_router(session_factory, lambda: _resolve_market_data_provider(
        "alpaca-market-data", resolved_market_data_providers, UiRepository(session_factory), market_data_http_client,
    )))
    from tradingagents.research.accounting_api import create_accounting_router
    app.include_router(create_accounting_router(session_factory, lambda: _resolve_broker_adapter(UiRepository(session_factory), resolved_broker_providers)))
    from tradingagents.research.deployment_api import create_deployment_router
    app.include_router(create_deployment_router(session_factory, lambda: _resolve_broker_adapter(UiRepository(session_factory), resolved_broker_providers)))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://host.docker.internal:3000",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def repository() -> UiRepository:
        return UiRepository(session_factory)

    def run_service(
        repository: UiRepository = Depends(repository),
    ) -> TradingRunService:
        real_runner = _resolve_research_runner(
            repository,
            resolved_real_runner,
            llm_client_factory=llm_client_factory,
        )
        return TradingRunService(repository, real_runner=real_runner)

    TradingRunService(UiRepository(session_factory)).fail_interrupted_runs(
        reason="server_restart"
    )

    def broker_service(repo: UiRepository = Depends(repository)) -> BrokerService:
        from tradingagents.research.accounting_repository import PaperAccountingRepository
        from tradingagents.research.accounting_service import ReconciledPaperBroker
        return BrokerService(
            repo,
            ReconciledPaperBroker(_resolve_broker_adapter(repo, resolved_broker_providers), PaperAccountingRepository(session_factory)),
            constraint_policy=_default_constraint_policy(),
        )

    from tradingagents.scheduling.api import create_scheduler_router
    app.include_router(create_scheduler_router(session_factory, lambda: broker_service(UiRepository(session_factory))))

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

    @app.get("/api/room-policies")
    def list_room_policy_catalog():
        return {"rooms": list_room_policies()}

    @app.post("/api/room-policies/evaluate")
    def evaluate_room_policy(request: RoomToolPolicyRequest):
        return evaluate_room_tool(request.room_id, request.tool_grant)

    @app.get("/api/provider-configs")
    def list_provider_configs(repo: UiRepository = Depends(repository)):
        return {"providers": repo.list_provider_configs()}

    @app.post("/api/provider-configs", status_code=201)
    def create_user_provider(
        request: UserProviderCreateRequest,
        repo: UiRepository = Depends(repository),
    ):
        try:
            record = repo.create_user_provider(
                name=request.name,
                kind=request.kind,
                base_url=request.base_url,
                model=request.model,
                api_key_env=request.api_key_env,
                role_models=request.role_models,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        repo.append_private_office_event(
            event_type="provider.user_created",
            summary=f"Added user-defined provider {record.name}.",
            actor="Provider Registry",
            entity_id=f"provider_{record.provider_id.replace(':', '_')}",
            payload={
                "provider_id": record.provider_id,
                "kind": request.kind,
                "base_url": request.base_url,
            },
        )
        return record

    @app.delete("/api/provider-configs/{provider_id}", status_code=204)
    def delete_user_provider(
        provider_id: str,
        repo: UiRepository = Depends(repository),
    ):
        try:
            repo.delete_user_provider(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Provider not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        repo.append_private_office_event(
            event_type="provider.user_deleted",
            summary=f"Removed user-defined provider {provider_id}.",
            actor="Provider Registry",
            entity_id=f"provider_{provider_id.replace(':', '_')}",
            payload={"provider_id": provider_id},
        )
        return None

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
                clear_secret_ref="secret_ref" in request.model_fields_set and request.secret_ref is None,
                config=request.config,
                health=request.health,
                status=request.status,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Provider not found") from exc

    @app.get("/api/provider-configs/{provider_id}/models")
    def list_provider_models(
        provider_id: str,
        repo: UiRepository = Depends(repository),
    ):
        """Best-effort model-list discovery for the dropdown UIs.

        Knows how to ask each provider kind for the models it offers
        (Codex CLI cache file, OpenAI-compatible /v1/models probe,
        Anthropic static list). Always returns ``{models, source}`` so
        the frontend can either populate a select or fall back to a
        free-text input when ``source == "unavailable"``.
        """
        from tradingagents.llm_clients.model_discovery import discover_models

        try:
            config = repo.get_provider_config(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Provider not found") from exc

        provider = str(config.config.get("provider") or "")
        base_url = config.config.get("base_url")
        default_headers: dict[str, str] = {}
        api_key: str | None = None

        if provider == "codex-oauth":
            # Codex discovery reads the local CLI cache; no api_key
            # forwarding needed.
            pass
        elif config.secret_ref:
            try:
                api_key = _secret_store_for_ref(config.secret_ref).get_secret(config.secret_ref)
            except (SecretNotFoundError, ValueError):
                return {"provider_id": provider_id, "models": [], "source": "unavailable",
                        "detail": "Configured model-discovery credential is unavailable"}

        result = discover_models(
            provider=provider,
            base_url=str(base_url) if isinstance(base_url, str) else None,
            api_key=api_key,
            default_headers=default_headers,
        )
        return {
            "provider_id": provider_id,
            "models": result.models,
            "source": result.source,
            "detail": result.detail,
        }

    @app.post("/api/provider-configs/{provider_id}/health-check")
    def check_provider_health(
        provider_id: str,
        repo: UiRepository = Depends(repository),
    ):
        try:
            config = repo.get_provider_config(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Provider not found") from exc

        secret_required = _provider_requires_secret(config.config)
        secret_health = (
            _describe_secret_ref(config.secret_ref)
            if secret_required
            else {"backend": "none", "available": True, "required": False}
        )
        status = "disabled" if not config.enabled else "available" if secret_health["available"] else "needs_key"
        health = {
            "check_kind": "credential_availability",
            "connection_verified": False,
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
                "secret_required": secret_required,
                "status": status,
            },
        )
        return updated

    @app.get("/api/provider-role-assignments")
    def list_provider_role_assignments(repo: UiRepository = Depends(repository)):
        from tradingagents.research.evidence.provider import SUPPORTED
        return {"assignments": repo.list_provider_role_assignments(), "strategy_research_protocols": sorted(SUPPORTED)}

    @app.get("/api/runtime/status", response_model=RuntimeStatusResponse)
    def runtime_status(repo: UiRepository = Depends(repository)) -> RuntimeStatusResponse:
        return _runtime_status(repo, resolved_real_runner)

    @app.post("/api/runtime/research-runner", response_model=RuntimeStatusResponse)
    def update_runtime_research_runner(
        request: RuntimeResearchRunnerRequest,
        repo: UiRepository = Depends(repository),
    ) -> RuntimeStatusResponse:
        repo.set_research_runner_mode(request.mode)
        repo.append_private_office_event(
            event_type="runtime.research_runner_updated",
            summary=f"Set research runner mode to {request.mode}.",
            actor="Settings",
            entity_id="runtime_research_runner",
            payload={"mode": request.mode},
        )
        return _runtime_status(repo, resolved_real_runner)

    @app.post("/api/runtime/developer-mode", response_model=RuntimeStatusResponse)
    def update_runtime_developer_mode(
        request: RuntimeDeveloperModeRequest,
        repo: UiRepository = Depends(repository),
    ) -> RuntimeStatusResponse:
        repo.set_developer_mode_enabled(request.enabled)
        repo.append_private_office_event(
            event_type="runtime.developer_mode_updated",
            summary=f"{'Enabled' if request.enabled else 'Disabled'} developer mode.",
            actor="Settings",
            entity_id="runtime_developer_mode",
            payload={"enabled": request.enabled},
        )
        return _runtime_status(repo, resolved_real_runner)

    @app.post("/api/provider-role-assignments/{role_key}")
    def update_provider_role_assignment(
        role_key: str,
        request: ProviderRoleAssignmentRequest,
        repo: UiRepository = Depends(repository),
    ):
        # Block assigning developer-tagged providers (e.g. Codex CLI bridge)
        # to any role unless the developer-mode toggle is on. The provider
        # itself stays in the catalog so the UI can show it with a
        # "requires developer mode" badge; this is the enforcement point.
        try:
            target_provider = repo.get_provider_config(request.provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Provider not found") from exc
        if (
            target_provider.config.get("developer_mode") is True
            and not repo.get_developer_mode_enabled()
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{target_provider.name} requires developer mode. "
                    "Enable developer mode in Settings before assigning it to a role."
                ),
            )
        if role_key in {"research_designer", "research_extractor"}:
            from tradingagents.research.evidence.provider import SUPPORTED
            protocol = str(target_provider.config.get("provider") or "openai").lower()
            if protocol not in SUPPORTED:
                raise HTTPException(status_code=400, detail="This provider has no verified strategy research adapter. Select Codex or a supported API provider.")
        try:
            assignment = repo.upsert_provider_role_assignment(
                role_key=role_key,
                provider_id=request.provider_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Provider not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        repo.append_private_office_event(
            event_type="provider.role_assignment_updated",
            summary=f"Routed provider role {role_key} to {request.provider_id}.",
            actor="Provider Registry",
            entity_id=f"provider_role_{role_key}",
            payload={
                "provider_id": request.provider_id,
                "surface": assignment.surface,
            },
        )
        return assignment

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

    @app.get("/api/approval-ledger")
    def list_approval_ledger(
        room_id: str | None = None,
        entity_id: str | None = None,
        repo: UiRepository = Depends(repository),
    ):
        return {
            "entries": repo.list_approval_ledger_entries(
                room_id=room_id,
                entity_id=entity_id,
            )
        }

    @app.post("/api/approval-ledger", response_model=ApprovalLedgerRecord)
    def record_approval_ledger_entry(
        request: ApprovalLedgerRequest,
        repo: UiRepository = Depends(repository),
    ) -> ApprovalLedgerRecord:
        try:
            return repo.record_approval_ledger_entry(
                room_id=request.room_id,
                source=request.source,
                entity_type=request.entity_type,
                entity_id=request.entity_id,
                action=request.action,
                actor=request.actor,
                summary=request.summary,
                payload=request.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/trade-theses")
    def list_trade_theses(
        symbol: str | None = None,
        status: str | None = None,
        target_room: str | None = None,
        repo: UiRepository = Depends(repository),
    ):
        return {
            "theses": repo.list_trade_theses(
                symbol=symbol,
                status=status,
                target_room=target_room,
            )
        }

    @app.post("/api/trade-theses", response_model=TradeThesisRecord)
    def create_trade_thesis(
        request: TradeThesisRequest,
        repo: UiRepository = Depends(repository),
    ) -> TradeThesisRecord:
        try:
            return repo.create_trade_thesis(
                symbol=request.symbol,
                source_report_id=request.source_report_id,
                source_room=request.source_room,
                target_room=request.target_room,
                direction=request.direction,
                horizon=request.horizon,
                conviction=request.conviction,
                thesis=request.thesis,
                catalysts=request.catalysts,
                invalidation=request.invalidation,
                risk_notes=request.risk_notes,
                status=request.status,
                payload=request.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/portfolio-reviews")
    def list_portfolio_reviews(
        limit: int | None = None,
        symbol: str | None = None,
        status: str | None = None,
        repo: UiRepository = Depends(repository),
    ):
        return {
            "reviews": repo.list_portfolio_reviews(
                limit=limit,
                symbol=symbol,
                status=status,
            )
        }

    @app.post("/api/portfolio-reviews", response_model=PortfolioReviewRecord)
    def create_portfolio_review(
        request: PortfolioReviewRequest,
        repo: UiRepository = Depends(repository),
    ) -> PortfolioReviewRecord:
        try:
            return repo.create_portfolio_review(
                symbol=request.symbol,
                room_id=request.room_id,
                status=request.status,
                goals=request.goals,
                horizon=request.horizon,
                risk_posture=request.risk_posture,
                sector_focus=request.sector_focus,
                constraints=request.constraints,
                liquidity_needs=request.liquidity_needs,
                thesis=request.thesis,
                missing_provider_facts=request.missing_provider_facts,
                payload=request.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/funding-allocation-reviews")
    def list_funding_allocation_reviews(
        limit: int | None = None,
        symbol: str | None = None,
        status: str | None = None,
        repo: UiRepository = Depends(repository),
    ):
        return {
            "reviews": repo.list_funding_allocation_reviews(
                limit=limit,
                symbol=symbol,
                status=status,
            )
        }

    @app.post(
        "/api/funding-allocation-reviews",
        response_model=FundingAllocationReviewRecord,
    )
    def create_funding_allocation_review(
        request: FundingAllocationReviewRequest,
        repo: UiRepository = Depends(repository),
    ) -> FundingAllocationReviewRecord:
        try:
            return repo.create_funding_allocation_review(
                symbol=request.symbol,
                source_thesis_id=request.source_thesis_id,
                execution_program_id=request.execution_program_id,
                status=request.status,
                notional=request.notional,
                tracks=request.tracks,
                missing_provider_facts=request.missing_provider_facts,
                approval_next_steps=request.approval_next_steps,
                payload=request.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/execution-programs")
    def list_execution_programs(
        limit: int | None = None,
        symbol: str | None = None,
        state: str | None = None,
        repo: UiRepository = Depends(repository),
    ):
        return {
            "programs": repo.list_execution_programs(
                limit=limit,
                symbol=symbol,
                state=state,
            )
        }

    @app.post("/api/execution-programs", response_model=ExecutionProgramRecord)
    def create_execution_program(
        request: ExecutionProgramRequest,
        repo: UiRepository = Depends(repository),
    ) -> ExecutionProgramRecord:
        try:
            return repo.create_execution_program(
                symbol=request.symbol,
                source_thesis_id=request.source_thesis_id,
                algorithm=request.algorithm,
                state=request.state,
                mode=request.mode,
                approval_status=request.approval_status,
                live_submission_enabled=request.live_submission_enabled,
                trigger_points=request.trigger_points,
                circuit_breakers=request.circuit_breakers,
                missing_provider_facts=request.missing_provider_facts,
                payload=request.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/execution-programs/{program_id}/events")
    def list_execution_program_events(
        program_id: str,
        repo: UiRepository = Depends(repository),
    ):
        try:
            return {
                "events": repo.list_execution_program_events(program_id)
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Execution program not found") from exc

    @app.post(
        "/api/execution-programs/{program_id}/events",
        response_model=ExecutionProgramEventRecord,
    )
    def append_execution_program_event(
        program_id: str,
        request: ExecutionProgramEventRequest,
        repo: UiRepository = Depends(repository),
    ) -> ExecutionProgramEventRecord:
        try:
            return repo.append_execution_program_event(
                program_id=program_id,
                event_type=request.event_type,
                summary=request.summary,
                payload=request.payload,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Execution program not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    @app.get("/api/agent-workflows")
    def list_agent_workflows(
        agent_class: str | None = None,
        repo: UiRepository = Depends(repository),
    ):
        return {
            "workflows": repo.list_agent_workflows(agent_class=agent_class)
        }

    @app.post("/api/agent-workflows")
    def create_agent_workflow(
        request: AgentWorkflowRequest,
        repo: UiRepository = Depends(repository),
    ):
        try:
            workflow = repo.create_agent_workflow(
                name=request.name,
                agent_class=request.agent_class,
                graph_runtime=request.graph_runtime,
                status=request.status,
                nodes=request.nodes,
                edges=request.edges,
                required_provider_roles=request.required_provider_roles,
                payload=request.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        repo.append_private_office_event(
            event_type="agent_workflow.created",
            summary=f"Created agent workflow: {request.name}.",
            actor="Agent Builder",
            entity_id=workflow.workflow_id,
            payload={
                "agent_class": request.agent_class,
                "graph_runtime": request.graph_runtime,
                "required_provider_roles": request.required_provider_roles,
            },
        )
        return workflow

    @app.get("/api/agent-operations")
    def list_agent_operations(
        limit: int | None = None,
        agent_id: str | None = None,
        room_id: str | None = None,
        symbol: str | None = None,
        operation_type: str | None = None,
        status: str | None = None,
        authority: str | None = None,
        repo: UiRepository = Depends(repository),
    ):
        return {
            "operations": repo.list_agent_operations(
                limit=limit,
                agent_id=agent_id,
                room_id=room_id,
                symbol=symbol,
                operation_type=operation_type,
                status=status,
                authority=authority,
            )
        }

    @app.post("/api/agent-operations", response_model=AgentOperationRecord)
    def create_agent_operation(
        request: AgentOperationRequest,
        repo: UiRepository = Depends(repository),
    ) -> AgentOperationRecord:
        try:
            return repo.create_agent_operation(
                agent_id=request.agent_id,
                agent_name=request.agent_name,
                room_id=request.room_id,
                symbol=request.symbol,
                operation_type=request.operation_type,
                authority=request.authority,
                source_workflow_id=request.source_workflow_id,
                linked_run_id=request.linked_run_id,
                linked_execution_program_id=request.linked_execution_program_id,
                payload=request.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post(
        "/api/agent-operations/{operation_id}/complete",
        response_model=AgentOperationRecord,
    )
    def complete_agent_operation(
        operation_id: str,
        request: AgentOperationCompleteRequest,
        repo: UiRepository = Depends(repository),
    ) -> AgentOperationRecord:
        try:
            return repo.update_agent_operation(
                operation_id,
                status="completed",
                linked_run_id=request.linked_run_id,
                linked_execution_program_id=request.linked_execution_program_id,
                payload=request.payload,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Agent operation not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/agent-packs")
    def list_agent_packs(repo: UiRepository = Depends(repository)):
        return {"packs": repo.list_agent_packs()}

    @app.post("/api/agent-packs/import", response_model=AgentPackImportResponse)
    def import_agent_pack_endpoint(
        request: AgentPackImportRequest,
        repo: UiRepository = Depends(repository),
    ) -> AgentPackImportResponse:
        try:
            result = import_agent_pack(
                request.source_path,
                repo,
                pack_id=request.pack_id,
                source_url=request.source_url,
                source_commit=request.source_commit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        repo.append_private_office_event(
            event_type="agent_pack.imported",
            summary=f"Imported agent pack: {request.pack_id}.",
            actor="Agent Pack Importer",
            entity_id=f"agent_pack_{request.pack_id.replace('-', '_')}",
            payload={
                "agent_count": result.agent_count,
                "skill_count": result.skill_count,
                "connector_count": result.connector_count,
                "source_url": request.source_url,
                "source_commit": request.source_commit,
            },
        )
        return AgentPackImportResponse(
            pack_id=result.pack.pack_id,
            agent_count=result.agent_count,
            skill_count=result.skill_count,
            connector_count=result.connector_count,
        )

    @app.get("/api/imported-agents")
    def list_imported_agents(
        pack_id: str | None = None,
        agent_class: str | None = None,
        repo: UiRepository = Depends(repository),
    ):
        return {
            "agents": repo.list_imported_agents(
                pack_id=pack_id,
                agent_class=agent_class,
            )
        }

    @app.get("/api/imported-skills")
    def list_imported_skills(
        pack_id: str | None = None,
        repo: UiRepository = Depends(repository),
    ):
        return {"skills": repo.list_imported_skills(pack_id=pack_id)}

    @app.get("/api/mcp-connectors")
    def list_mcp_connectors(repo: UiRepository = Depends(repository)):
        return {"connectors": repo.list_mcp_connectors()}

    @app.get("/api/snapshots", response_model=SnapshotsResponse)
    def list_snapshots(repo: UiRepository = Depends(repository)) -> SnapshotsResponse:
        """Return all stored snapshot manifests, newest first.

        SettingsDrawer pulls this on mount to render the existing-backups
        list. ``items`` is the catalog-shape envelope all frontend code
        already expects.
        """

        manifests = sorted(
            repo.list_snapshot_manifests(),
            key=lambda record: record.created_at,
            reverse=True,
        )
        return SnapshotsResponse(items=manifests)

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
                artifact_root=Path(os.environ.get("TRADEMASTER_RESEARCH_ARTIFACTS", str(database_path.resolve().parent / ".research-artifacts"))),
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

    @app.get("/api/discover/explorer", response_model=ExplorerResponse)
    def get_research_explorer(repo: UiRepository = Depends(repository)) -> ExplorerResponse:
        provider, _ = _resolve_market_data_provider(
            "alpaca-market-data", resolved_market_data_providers, repo, market_data_http_client,
        )
        return explore_market(provider)

    @app.get("/api/discover/candidates", response_model=DiscoverCandidatesResponse)
    def get_discover_candidates(
        limit: int = 20,
        exclude: str | None = None,
        min_price: float = 5.0,
        repo: UiRepository = Depends(repository),
    ) -> DiscoverCandidatesResponse:
        """Candidate tickers outside the watchlist, from the Alpaca stock screener.

        Merges movers (gainers/losers) and most-actives, drops excluded and
        sub-``min_price`` symbols, and returns at most ``limit`` candidates.
        """
        clamped_limit = max(1, min(limit, 50))
        provider, _provider_config = _resolve_market_data_provider(
            "alpaca-market-data",
            resolved_market_data_providers,
            repo,
            market_data_http_client,
        )
        fetch_movers = getattr(provider, "stock_movers", None)
        fetch_most_actives = getattr(provider, "most_active_stocks", None)
        if fetch_movers is None or fetch_most_actives is None:
            raise HTTPException(
                status_code=503,
                detail="Configured market data provider does not support the stock screener",
            )
        try:
            movers, most_actives = _cached_screener_payloads(
                lambda: fetch_movers(top=25),
                lambda: fetch_most_actives(by="volume", top=25),
            )
        except SecretNotFoundError as exc:
            raise HTTPException(
                status_code=403,
                detail="Market data secret is not available",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail=f"Alpaca screener request failed: {exc}",
            ) from exc
        exclude_symbols = exclude.split(",") if exclude else []
        candidates = _build_discover_candidates(
            movers,
            most_actives,
            exclude=exclude_symbols,
            min_price=min_price,
            limit=clamped_limit,
            news_items=_cached_general_news_items(),
        )
        return DiscoverCandidatesResponse(candidates=candidates)

    @app.get("/api/news", response_model=NewsResponse)
    def get_company_news(
        symbol: str,
        since_hours: int = 24,
        limit: int = 20,
    ) -> NewsResponse:
        """
        Recent company news for `symbol` over the last `since_hours` window.

        Backed by Finnhub today. Requires FINNHUB_API_KEY in the process env.
        Returns 503 if the key is missing or the upstream API rejects the call;
        the frontend renders that as a "wire Finnhub" empty state.
        """

        symbol_normalized = symbol.strip().upper()
        if not symbol_normalized:
            raise HTTPException(status_code=400, detail="symbol is required")

        if since_hours <= 0 or since_hours > 24 * 14:
            raise HTTPException(
                status_code=400,
                detail="since_hours must be between 1 and 336",
            )

        now = datetime.now(timezone.utc)
        end_date = now.date().isoformat()
        # Pad the lower bound by a day so we don't miss news straddling midnight UTC.
        lookback_days = max(1, (since_hours // 24) + 1)
        start = (now.date() - timedelta(days=lookback_days)).isoformat()

        try:
            raw_items = fetch_company_news(
                symbol_normalized,
                start_date=start,
                end_date=end_date,
            )
        except FinnhubError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Finnhub request failed: {exc}",
            ) from exc

        cutoff_ts = (now - timedelta(hours=since_hours)).timestamp()
        filtered: list[NewsItem] = []
        for entry in raw_items:
            ts = entry.get("datetime")
            if isinstance(ts, (int, float)) and ts < cutoff_ts:
                continue
            filtered.append(NewsItem(**normalize_news_item(entry)))
            if len(filtered) >= limit:
                break

        return NewsResponse(
            symbol=symbol_normalized,
            since_hours=since_hours,
            items=filtered,
        )

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

    @app.get("/api/execution-algorithms")
    def list_execution_algorithm_catalogue() -> dict[str, Any]:
        """Return every registered execution algorithm grouped by category.

        Backs the Brokerage Floor's algorithm picker. The frontend cards are
        rendered from this response; selecting one fires a POST to the
        sibling /preview endpoint with the selected name and any user
        overrides in `parameters`.
        """

        # Stable, user-facing label per category.
        labels = {
            "time_based": "Time-based",
            "momentum": "Momentum",
            "mean_reversion": "Mean-Reversion",
            "volatility": "Volatility",
            "microstructure": "Microstructure",
            "event_driven": "Event-driven",
        }
        grouped = _list_algorithms_by_category()
        categories = []
        total = 0
        for category_id, classes in grouped.items():
            algorithms = [
                {
                    "name": cls.name,
                    "category": cls.category,
                    "description": cls.description,
                }
                for cls in classes
            ]
            total += len(algorithms)
            categories.append(
                {
                    "id": category_id,
                    "label": labels.get(category_id, category_id.replace("_", " ").title()),
                    "count": len(algorithms),
                    "algorithms": algorithms,
                }
            )
        return {"categories": categories, "total": total}

    @app.post(
        "/api/execution-algorithms/preview",
        response_model=ExecutionAlgorithmPlan,
    )
    def preview_algorithm(
        request: ExecutionAlgorithmPreviewRequest,
    ) -> ExecutionAlgorithmPlan:
        try:
            enforce_room_tool(request.room_id, "execution-algorithm-preview")
            return preview_execution_algorithm(
                algorithm=request.algorithm,
                symbol=request.symbol,
                side=request.side,
                notional=request.notional,
                reference_price=request.reference_price,
                parameters=request.parameters,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get("/api/runs", response_model=RunsResponse)
    def list_runs(
        ticker: str | None = None,
        limit: int = 25,
        repo: UiRepository = Depends(repository),
    ) -> RunsResponse:
        normalized_ticker = ticker.strip().upper() if ticker else None
        bounded_limit = max(1, min(limit, 100))
        runs = repo.list_runs()
        if normalized_ticker:
            runs = [run for run in runs if run.ticker == normalized_ticker]
        return RunsResponse(runs=runs[:bounded_limit])

    @app.get("/api/report-schedules", response_model=ReportSchedulesResponse)
    def list_report_schedules(
        symbol: str | None = None,
        enabled: bool | None = None,
        repo: UiRepository = Depends(repository),
    ) -> ReportSchedulesResponse:
        return ReportSchedulesResponse(
            schedules=repo.list_report_schedules(symbol=symbol, enabled=enabled)
        )

    @app.post("/api/report-schedules", response_model=ReportScheduleRecord)
    def create_report_schedule(
        request: ReportScheduleRequest,
        repo: UiRepository = Depends(repository),
    ) -> ReportScheduleRecord:
        try:
            schedule = repo.create_report_schedule(
                name=request.name,
                symbol=request.symbol,
                cadence=request.cadence,
                broker_mode=request.broker_mode,
                execution_mode=request.execution_mode,
                enabled=request.enabled,
                payload=request.payload,
            )
            if schedule.enabled and schedule.cadence != "manual":
                repo.create_agent_trigger(
                    name=f"{schedule.name} wakeup",
                    room_id="market",
                    trigger_type="time",
                    target_agent="scheduled-perception-agent",
                    symbol=schedule.symbol,
                    condition={
                        "cadence": schedule.cadence,
                        "source": "report_schedule",
                    },
                    workflow_id=schedule.schedule_id,
                    enabled=True,
                    payload={
                        "schedule_id": schedule.schedule_id,
                        "perception": request.payload.get("perception", "scheduled_research"),
                    },
                )
            return schedule
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/agent-triggers")
    def list_agent_triggers(
        room_id: str | None = None,
        symbol: str | None = None,
        enabled: bool | None = None,
        repo: UiRepository = Depends(repository),
    ):
        return {
            "triggers": repo.list_agent_triggers(
                room_id=room_id,
                symbol=symbol,
                enabled=enabled,
            )
        }

    @app.post("/api/agent-triggers", response_model=AgentTriggerRecord)
    def create_agent_trigger(
        request: AgentTriggerRequest,
        repo: UiRepository = Depends(repository),
    ) -> AgentTriggerRecord:
        try:
            return repo.create_agent_trigger(
                name=request.name,
                room_id=request.room_id,
                trigger_type=request.trigger_type,
                target_agent=request.target_agent,
                symbol=request.symbol,
                condition=request.condition,
                workflow_id=request.workflow_id,
                enabled=request.enabled,
                payload=request.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agent-triggers/evaluate")
    def evaluate_agent_trigger_harness(
        request: AgentTriggerEvaluationRequest,
        repo: UiRepository = Depends(repository),
    ):
        symbol = request.symbol or request.event.get("symbol")
        triggers = repo.list_agent_triggers(
            room_id=request.room_id,
            symbol=symbol if isinstance(symbol, str) else None,
            enabled=True,
        )
        return evaluate_agent_triggers(triggers, request.event).to_dict()

    @app.post(
        "/api/report-schedules/trigger-enabled",
        response_model=ReportScheduleBulkTriggerResponse,
    )
    def trigger_enabled_report_schedules(
        symbol: str | None = None,
        repo: UiRepository = Depends(repository),
        service: TradingRunService = Depends(run_service),
    ) -> ReportScheduleBulkTriggerResponse:
        schedules = repo.list_report_schedules(symbol=symbol, enabled=True)
        results: list[ReportScheduleTriggerResponse] = []
        for schedule in schedules:
            run = service.start_run(
                RunConfig(
                    ticker=schedule.symbol,
                    trade_date=date.today().isoformat(),
                    broker_mode=schedule.broker_mode,
                    execution_mode=schedule.execution_mode,
                )
            )
            updated_schedule = repo.mark_report_schedule_run(schedule.schedule_id, run.run_id)
            results.append(ReportScheduleTriggerResponse(schedule=updated_schedule, run=run))
        return ReportScheduleBulkTriggerResponse(
            triggered_count=len(results),
            results=results,
        )

    @app.post(
        "/api/report-schedules/{schedule_id}/trigger",
        response_model=ReportScheduleTriggerResponse,
    )
    def trigger_report_schedule(
        schedule_id: str,
        repo: UiRepository = Depends(repository),
        service: TradingRunService = Depends(run_service),
    ) -> ReportScheduleTriggerResponse:
        try:
            schedule = repo.get_report_schedule(schedule_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Report schedule not found") from exc
        if not schedule.enabled:
            raise HTTPException(status_code=400, detail="Report schedule is disabled")
        run = service.start_run(
            RunConfig(
                ticker=schedule.symbol,
                trade_date=date.today().isoformat(),
                broker_mode=schedule.broker_mode,
                execution_mode=schedule.execution_mode,
            )
        )
        updated_schedule = repo.mark_report_schedule_run(schedule.schedule_id, run.run_id)
        return ReportScheduleTriggerResponse(schedule=updated_schedule, run=run)

    def _start_run(service: TradingRunService, config: RunConfig) -> RunCreated:
        """Start one run the same way ``POST /api/runs`` does.

        ``execution_mode == "real"`` queues the run and completes it on a
        daemon thread (full TradingAgents research path); anything else runs
        the simulated event script synchronously.
        """

        if config.execution_mode == "real":
            created = service.queue_real_run(config)
            thread = threading.Thread(
                target=service.complete_queued_real_run,
                args=(created.run_id, config),
                daemon=True,
                name=f"trademaster-run-{created.run_id}",
            )
            thread.start()
            return created
        return service.start_run(config)

    @app.post("/api/runs", response_model=RunCreated)
    def create_run(
        config: RunConfig,
        service: TradingRunService = Depends(run_service),
    ) -> RunCreated:
        return _start_run(service, config)

    @app.get("/api/scans/verdicts", response_model=ScanVerdictsResponse)
    def get_scan_verdicts(
        symbols: str | None = None,
        limit: int = 50,
        repo: UiRepository = Depends(repository),
    ) -> ScanVerdictsResponse:
        requested = (
            [part.strip().upper() for part in symbols.split(",") if part.strip()]
            if symbols
            else None
        )
        bounded_limit = max(1, min(limit, 100))
        rows = repo.latest_completed_runs_by_symbol(requested, bounded_limit)
        verdicts: list[ScanVerdict] = []
        for summary, payload in rows:
            decision = payload or {}
            raw_confidence = decision.get("confidence")
            if raw_confidence is None:
                raw_confidence = decision.get("probability")
            try:
                confidence = float(raw_confidence) if raw_confidence is not None else None
            except (TypeError, ValueError):
                confidence = None
            thesis = decision.get("thesis")
            verdicts.append(
                ScanVerdict(
                    symbol=summary.ticker,
                    rating=summary.final_rating,
                    action=summary.final_action,
                    thesis=str(thesis) if thesis is not None else None,
                    confidence=confidence,
                    run_id=summary.run_id,
                    run_created_at=summary.created_at,
                )
            )
        return ScanVerdictsResponse(verdicts=verdicts)

    @app.post("/api/scans", response_model=ScanStartedResponse)
    def start_scan(
        request: ScanRequest,
        service: TradingRunService = Depends(run_service),
    ) -> ScanStartedResponse:
        trade_date = datetime.now(timezone.utc).date().isoformat()
        started: list[ScanStartedEntry] = []
        failed: list[ScanFailedEntry] = []
        for raw_symbol in request.symbols:
            symbol = raw_symbol.strip().upper()
            try:
                config = RunConfig(
                    ticker=symbol,
                    trade_date=trade_date,
                    broker_mode="disabled",
                    execution_mode="real",
                )
                created = _start_run(service, config)
                started.append(ScanStartedEntry(symbol=symbol, run_id=created.run_id))
            except Exception as exc:  # noqa: BLE001 — one bad symbol must not sink the batch
                failed.append(ScanFailedEntry(symbol=symbol or raw_symbol, error=str(exc)))
        return ScanStartedResponse(started=started, failed=failed)

    @app.post("/api/quickscan", response_model=QuickScanResponse)
    def quick_scan(
        request: QuickScanRequest,
        repo: UiRepository = Depends(repository),
    ) -> QuickScanResponse:
        """Cheap wide-pass screen: one gpt-4o-mini verdict per symbol, in parallel.

        Context (quote/daily change/headlines) is best-effort — missing data
        degrades the prompt, never the call. Results are persisted per symbol.
        """
        symbols: list[str] = []
        for raw_symbol in request.symbols:
            symbol = raw_symbol.strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        if not symbols:
            raise HTTPException(status_code=422, detail="no valid symbols provided")

        provider, feed = _resolve_watcher_market_data()
        outcomes, failures = run_quick_scan(symbols, provider, feed=feed)

        results: list[QuickScanResult] = []
        failed = [
            QuickScanFailedEntry(symbol=failure.symbol, error=failure.error)
            for failure in failures
        ]
        for outcome in outcomes:
            try:
                record = repo.insert_quick_scan(
                    symbol=outcome.symbol,
                    stance=outcome.stance,
                    conviction=outcome.conviction,
                    thesis=outcome.thesis,
                    catalyst=outcome.catalyst,
                    risk=outcome.risk,
                    model=outcome.model,
                )
            except Exception as exc:  # noqa: BLE001 — persistence failure surfaces per symbol
                failed.append(QuickScanFailedEntry(symbol=outcome.symbol, error=str(exc)))
                continue
            results.append(
                QuickScanResult(
                    symbol=record.symbol,
                    stance=record.stance,  # type: ignore[arg-type]
                    conviction=record.conviction,
                    thesis=record.thesis,
                    catalyst=record.catalyst,
                    risk=record.risk,
                    model=record.model,
                    created_at=record.created_at,
                )
            )
        results.sort(key=lambda result: result.conviction, reverse=True)
        return QuickScanResponse(results=results, failed=failed)

    @app.get("/api/quickscan/latest", response_model=QuickScanResponse)
    def latest_quick_scans(
        symbols: str | None = None,
        limit: int = 50,
        repo: UiRepository = Depends(repository),
    ) -> QuickScanResponse:
        """Latest stored quick-scan row per symbol (all scanned symbols when omitted)."""
        requested = (
            [part.strip().upper() for part in symbols.split(",") if part.strip()]
            if symbols
            else None
        )
        bounded_limit = max(1, min(limit, 200))
        records = repo.latest_quick_scans(requested, bounded_limit)
        return QuickScanResponse(
            results=[
                QuickScanResult(
                    symbol=record.symbol,
                    stance=record.stance,  # type: ignore[arg-type]
                    conviction=record.conviction,
                    thesis=record.thesis,
                    catalyst=record.catalyst,
                    risk=record.risk,
                    model=record.model,
                    created_at=record.created_at,
                )
                for record in records
            ]
        )

    # Bare-array response is intentional here: this endpoint is polled by
    # `waitForRunEvents` and the SSE stream parser, both of which treat the
    # payload as a sequence of events with no envelope overhead.
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
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                # Disable nginx proxy buffering so each event flushes
                # immediately to the browser.
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/trades/open", response_model=OpenTradesResponse)
    def list_open_trades(
        symbol: str | None = None,
        limit: int = 50,
        repo: UiRepository = Depends(repository),
    ) -> OpenTradesResponse:
        """
        Trade intents currently in flight (status NOT IN {filled, canceled,
        rejected, expired, done}), paired with their latest broker order if
        present. Most recently-updated first.
        """

        if limit <= 0 or limit > 200:
            raise HTTPException(status_code=400, detail="limit must be 1..200")

        rows = repo.list_open_trades(symbol=symbol, limit=limit)
        items: list[OpenTrade] = []
        for intent, order in rows:
            items.append(
                OpenTrade(
                    intent_id=intent.intent_id,
                    run_id=intent.run_id,
                    symbol=intent.symbol,
                    side=intent.side,
                    notional=intent.notional,
                    order_type=intent.order_type,
                    status=intent.status,
                    created_at=intent.created_at.isoformat(),
                    updated_at=intent.updated_at.isoformat(),
                    broker=(order.broker if order is not None else None),
                    broker_environment=(order.environment if order is not None else None),
                    broker_status=(order.status if order is not None else None),
                    broker_order_id=(order.broker_order_id if order is not None else None),
                    execution_schedule_id=intent.payload.get("execution_schedule_id"),
                )
            )
        return OpenTradesResponse(items=items)

    @app.post("/api/trades/preview")
    def preview_trade(
        request: TradePreviewRequest,
        service: BrokerService = Depends(broker_service),
    ):
        try:
            enforce_room_tool(request.room_id, "broker-paper-preview")
            # Hand the protective-stop envelope to the service so it
            # can persist on the intent payload. submit_approved_order
            # rehydrates it later and decides whether to plumb the
            # bracket through to the broker (broker_protective) or
            # leave the figures advisory-only.
            return service.preview_order(
                run_id=request.run_id,
                symbol=request.symbol,
                side=request.side,
                notional=request.notional,
                risk_controls=(
                    request.risk_controls.model_dump()
                    if request.risk_controls is not None
                    else None
                ),
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
            service.approve_order(intent_id, actor=request.actor, expected_order_hash=request.expected_order_hash)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trade or run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"intent_id": intent_id, "status": "approved"}

    @app.post("/api/trades/{intent_id}/cancel")
    def cancel_trade(
        intent_id: str,
        request: ApprovalRequest,
        service: BrokerService = Depends(broker_service),
    ) -> dict[str, str]:
        """Revoke a preview or request broker cancellation, retaining pending reservations."""

        try:
            status = service.cancel_order(intent_id, actor=request.actor)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trade or run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return {"intent_id": intent_id, "status": status}

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

    @app.get("/api/trades/{intent_id}/execution")
    def trade_execution(intent_id: str, service: BrokerService = Depends(broker_service)):
        try:
            return service.execution_history(intent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trade not found") from exc

    @app.post("/api/trades/{intent_id}/reconcile")
    def reconcile_trade(intent_id: str, service: BrokerService = Depends(broker_service)):
        try:
            return service.reconcile_order(intent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Trade not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Watcher primitive routes
    # ------------------------------------------------------------------

    def _resolve_watcher_market_data() -> tuple[MarketDataProvider | None, str | None]:
        """Lazy resolver for the firing loop and /check endpoint.

        Returns ``(provider, feed)``. Provider is None when alpaca-market-data
        is not configured or disabled — callers should treat that as a soft
        skip (loop logs warning, /check returns 503).
        """
        repo = UiRepository(session_factory)
        try:
            config = repo.get_provider_config("alpaca-market-data")
        except KeyError:
            return None, None
        if not config.enabled or config.secret_ref is None:
            return None, None
        provider = resolved_market_data_providers.get("alpaca-market-data")
        if provider is None:
            provider = AlpacaMarketDataProvider(
                secret_store=_secret_store_for_ref(config.secret_ref),
                secret_ref=config.secret_ref,
                http_client=market_data_http_client,
            )
        feed = _configured_feed(config.config)
        return provider, feed

    def _watcher_to_model(record) -> Watcher:
        return Watcher(
            watcher_id=record.watcher_id,
            name=record.name,
            symbol=record.symbol,
            condition_type=record.condition_type,
            threshold=record.threshold,
            enabled=record.enabled,
            payload=dict(record.payload or {}),
            linked_position_id=record.linked_position_id,
            linked_run_id=record.linked_run_id,
            last_fired_at=record.last_fired_at.isoformat() if record.last_fired_at else None,
            fire_count=record.fire_count or 0,
            created_at=record.created_at.isoformat(),
            updated_at=record.updated_at.isoformat(),
        )

    def _watcher_fire_to_model(record) -> WatcherFire:
        return WatcherFire(
            fire_id=record.fire_id,
            watcher_id=record.watcher_id,
            symbol=record.symbol,
            fired_at=record.fired_at.isoformat(),
            observed_value=record.observed_value,
            threshold=record.threshold,
            condition_type=record.condition_type,
            payload=dict(record.payload or {}),
        )

    @app.get("/api/watchers", response_model=WatcherCatalog)
    def list_watchers_route(
        symbol: str | None = None,
        enabled: bool | None = None,
        limit: int = 100,
        repo: UiRepository = Depends(repository),
    ) -> WatcherCatalog:
        records = repo.list_watchers(symbol=symbol, enabled=enabled, limit=limit)
        return WatcherCatalog(watchers=[_watcher_to_model(r) for r in records])

    @app.post("/api/watchers", response_model=Watcher, status_code=201)
    def create_watcher_route(
        request: CreateWatcherRequest,
        repo: UiRepository = Depends(repository),
    ) -> Watcher:
        try:
            record = repo.create_watcher(
                name=request.name,
                symbol=request.symbol,
                condition_type=request.condition_type,
                threshold=request.threshold,
                enabled=request.enabled,
                cooldown_seconds=request.cooldown_seconds,
                linked_position_id=request.linked_position_id,
                linked_run_id=request.linked_run_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _watcher_to_model(record)

    @app.get("/api/watchers/{watcher_id}", response_model=Watcher)
    def get_watcher_route(
        watcher_id: str,
        repo: UiRepository = Depends(repository),
    ) -> Watcher:
        try:
            record = repo.get_watcher(watcher_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Watcher not found") from exc
        return _watcher_to_model(record)

    @app.patch("/api/watchers/{watcher_id}", response_model=Watcher)
    def update_watcher_route(
        watcher_id: str,
        request: UpdateWatcherRequest,
        repo: UiRepository = Depends(repository),
    ) -> Watcher:
        try:
            record = repo.update_watcher(
                watcher_id,
                name=request.name,
                threshold=request.threshold,
                enabled=request.enabled,
                cooldown_seconds=request.cooldown_seconds,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Watcher not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _watcher_to_model(record)

    @app.delete("/api/watchers/{watcher_id}")
    def delete_watcher_route(
        watcher_id: str,
        repo: UiRepository = Depends(repository),
    ) -> dict[str, object]:
        try:
            repo.delete_watcher(watcher_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Watcher not found") from exc
        return {"watcher_id": watcher_id, "deleted": True}

    @app.get("/api/watcher-fires", response_model=WatcherFiresCatalog)
    def list_watcher_fires_route(
        watcher_id: str | None = None,
        symbol: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        repo: UiRepository = Depends(repository),
    ) -> WatcherFiresCatalog:
        records = repo.list_watcher_fires(
            watcher_id=watcher_id,
            symbol=symbol,
            since=since,
            limit=limit,
        )
        return WatcherFiresCatalog(fires=[_watcher_fire_to_model(r) for r in records])

    @app.post("/api/watchers/{watcher_id}/check")
    def check_watcher_route(
        watcher_id: str,
        repo: UiRepository = Depends(repository),
    ) -> dict[str, object]:
        try:
            watcher = repo.get_watcher(watcher_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Watcher not found") from exc
        provider, feed = _resolve_watcher_market_data()
        if provider is None:
            raise HTTPException(
                status_code=503,
                detail="Market data provider (alpaca-market-data) is not configured",
            )
        try:
            evaluation, fire, cooldown = _check_watcher_once(
                repo, watcher, provider, feed=feed
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "watcher_id": watcher_id,
            "fired": evaluation.fired,
            "in_cooldown": cooldown,
            "observed_value": evaluation.observed_value,
            "threshold": evaluation.threshold,
            "condition_type": evaluation.condition_type,
            "payload": evaluation.payload,
            "fire": _watcher_fire_to_model(fire).model_dump() if fire else None,
        }

    # ------------------------------------------------------------------
    # Watcher firing loop lifecycle
    # ------------------------------------------------------------------

    app.state.watcher_loop_task = None
    app.state.watcher_loop_stop = None
    app.state.deployment_recovery_task = None
    app.state.deployment_recovery_stop = None

    @on_lifecycle(app, "startup")
    async def _start_deployment_recovery() -> None:
        from tradingagents.research.deployment_jobs import DeploymentJobs
        jobs=DeploymentJobs(session_factory)
        stop=asyncio.Event()
        async def recover_once():
            try:
                await asyncio.to_thread(jobs.recover_expired)
                app.state.deployment_recovery_error=None
            except Exception as exc:
                app.state.deployment_recovery_error=type(exc).__name__
        await recover_once()
        async def run():
            while not stop.is_set():
                try: await asyncio.wait_for(stop.wait(),timeout=5)
                except asyncio.TimeoutError: await recover_once()
        app.state.deployment_recovery_stop=stop
        app.state.deployment_recovery_task=asyncio.create_task(run())

    @on_lifecycle(app, "shutdown")
    async def _stop_deployment_recovery() -> None:
        if app.state.deployment_recovery_stop is not None: app.state.deployment_recovery_stop.set()
        task=app.state.deployment_recovery_task
        if task is not None:
            try: await asyncio.wait_for(task,timeout=5)
            except (asyncio.TimeoutError,asyncio.CancelledError): task.cancel()

    @on_lifecycle(app, "startup")
    async def _start_watcher_loop() -> None:
        repo = UiRepository(session_factory)
        task, stop_event = _start_watcher_firing_loop(
            repo,
            _resolve_watcher_market_data,
            interval_seconds=_WATCHER_POLL_INTERVAL_SECONDS,
        )
        app.state.watcher_loop_task = task
        app.state.watcher_loop_stop = stop_event

    @on_lifecycle(app, "shutdown")
    async def _stop_watcher_loop() -> None:
        stop_event = app.state.watcher_loop_stop
        task = app.state.watcher_loop_task
        if stop_event is not None:
            stop_event.set()
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                task.cancel()

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


_DISCOVER_SCREENER_CACHE_TTL_SECONDS = 60.0
_discover_screener_cache: dict[str, object] = {"fetched_at": 0.0, "payload": None}
_discover_screener_cache_lock = threading.Lock()


def _cached_screener_payloads(
    fetch_movers: Callable[[], dict[str, Any]],
    fetch_most_actives: Callable[[], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch (movers, most_actives), reusing an in-process cache for 60s."""
    with _discover_screener_cache_lock:
        payload = _discover_screener_cache["payload"]
        fetched_at = float(_discover_screener_cache["fetched_at"])  # type: ignore[arg-type]
        if (
            payload is not None
            and time.monotonic() - fetched_at < _DISCOVER_SCREENER_CACHE_TTL_SECONDS
        ):
            return payload  # type: ignore[return-value]
    movers = fetch_movers()
    most_actives = fetch_most_actives()
    with _discover_screener_cache_lock:
        _discover_screener_cache["payload"] = (movers, most_actives)
        _discover_screener_cache["fetched_at"] = time.monotonic()
    return movers, most_actives


def _discover_maybe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _discover_maybe_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return None


_DISCOVER_SOURCE_PRIORITY = {"gainer": 0, "loser": 1, "most_active": 2, "news": 3}

_DISCOVER_NEWS_CACHE_TTL_SECONDS = 60.0
_discover_news_cache: dict[str, object] = {"fetched_at": 0.0, "items": None}
_discover_news_cache_lock = threading.Lock()


def _cached_general_news_items() -> list[dict[str, Any]]:
    """General market headlines for the "news" discovery source (60s cache).

    Best-effort: a missing FINNHUB_API_KEY or an upstream error silently
    contributes nothing — the screener sources still populate the funnel.
    """
    with _discover_news_cache_lock:
        items = _discover_news_cache["items"]
        fetched_at = float(_discover_news_cache["fetched_at"])  # type: ignore[arg-type]
        if items is not None and time.monotonic() - fetched_at < _DISCOVER_NEWS_CACHE_TTL_SECONDS:
            return items  # type: ignore[return-value]
    try:
        fresh = fetch_general_news()
    except Exception:  # noqa: BLE001 — includes FinnhubError for a missing key
        return []
    with _discover_news_cache_lock:
        _discover_news_cache["items"] = fresh
        _discover_news_cache["fetched_at"] = time.monotonic()
    return fresh


def _build_discover_candidates(
    movers: Mapping[str, Any],
    most_actives: Mapping[str, Any],
    *,
    exclude: list[str],
    min_price: float,
    limit: int,
    news_items: list[dict[str, Any]] | None = None,
) -> list[DiscoverCandidate]:
    excluded = {symbol.strip().upper() for symbol in exclude if symbol.strip()}
    by_symbol: dict[str, DiscoverCandidate] = {}
    price_dropped: set[str] = set()

    def add(
        raw_symbol: object,
        *,
        price: float | None,
        change_pct: float | None,
        volume: int | None,
        source: str,
    ) -> None:
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol or "." in symbol or "/" in symbol:
            return
        if symbol in excluded or symbol in price_dropped:
            return
        if price is not None and price < min_price:
            price_dropped.add(symbol)
            by_symbol.pop(symbol, None)
            return
        existing = by_symbol.get(symbol)
        if existing is not None:
            if source not in existing.sources:
                existing.sources.append(source)
            if existing.price is None:
                existing.price = price
            if existing.change_pct is None:
                existing.change_pct = change_pct
            if existing.volume is None:
                existing.volume = volume
            return
        by_symbol[symbol] = DiscoverCandidate(
            symbol=symbol,
            price=price,
            change_pct=change_pct,
            volume=volume,
            source=source,
            sources=[source],
        )

    for entry in movers.get("gainers") or []:
        add(
            entry.get("symbol"),
            price=_discover_maybe_float(entry.get("price")),
            change_pct=_discover_maybe_float(entry.get("percent_change")),
            volume=None,
            source="gainer",
        )
    for entry in movers.get("losers") or []:
        add(
            entry.get("symbol"),
            price=_discover_maybe_float(entry.get("price")),
            change_pct=_discover_maybe_float(entry.get("percent_change")),
            volume=None,
            source="loser",
        )
    for entry in most_actives.get("most_actives") or []:
        add(
            entry.get("symbol"),
            price=None,
            change_pct=None,
            volume=_discover_maybe_int(entry.get("volume")),
            source="most_active",
        )
    # News-driven candidates: symbols mined from general-market headlines'
    # "related" CSV. Price/change/volume stay null, and null-priced candidates
    # are never price-filtered (consistent with most-actives handling).
    for item in news_items or []:
        related = str(item.get("related") or "")
        for raw_related_symbol in related.split(","):
            add(
                raw_related_symbol,
                price=None,
                change_pct=None,
                volume=None,
                source="news",
            )

    def sort_key(candidate: DiscoverCandidate) -> tuple[int, float]:
        rank = _DISCOVER_SOURCE_PRIORITY.get(candidate.source, 3)
        if candidate.source == "gainer":
            metric = -(candidate.change_pct or 0.0)
        elif candidate.source == "loser":
            metric = -abs(candidate.change_pct or 0.0)
        else:
            metric = -float(candidate.volume or 0)
        return (rank, metric)

    return sorted(by_symbol.values(), key=sort_key)[:limit]


def _resolve_broker_adapter(
    repo: UiRepository,
    providers: Mapping[str, BrokerAdapter],
) -> BrokerAdapter:
    assignments = {row.role_key: row.provider_id for row in repo.list_provider_role_assignments()}
    provider_id = assignments.get("broker", "alpaca-paper-broker")
    # Fixtures are supplied explicitly by test harnesses; an unconfigured desk must not invent an account.
    fixture = providers.get("fixture-paper-broker")
    try:
        config = repo.get_provider_config(provider_id)
    except KeyError:
        raise HTTPException(status_code=503, detail="Assigned paper broker is not configured") from None
    if not config.enabled:
        if fixture is not None and provider_id == "alpaca-paper-broker":
            return fixture
        raise HTTPException(status_code=503, detail="Assigned paper broker is disabled")
    provider = providers.get(provider_id)
    if provider is not None:
        return provider
    if provider_id != "alpaca-paper-broker":
        raise HTTPException(status_code=503, detail="Assigned broker has no installed paper execution adapter")
    if config.secret_ref is None:
        if fixture is not None:
            return fixture
        raise HTTPException(status_code=503, detail="Assigned paper broker needs a credential reference")
    return AlpacaPaperBroker(
        secret_store=_secret_store_for_ref(config.secret_ref),
        secret_ref=config.secret_ref,
        price_estimator=_alpaca_price_estimator(config.secret_ref),
        base_url=_configured_alpaca_broker_base_url(config.config),
    )


def _runtime_status(
    repo: UiRepository,
    resolved_real_runner: RealRunRunner | None,
) -> RuntimeStatusResponse:
    policy = _default_constraint_policy()
    assignments = repo.list_provider_role_assignments()
    role_provider = {assignment.role_key: assignment.provider_id for assignment in assignments}
    research_provider_id = str(role_provider.get("research_llm") or "openai-llm")
    broker_provider_id = str(role_provider.get("broker") or "alpaca-paper-broker")
    research_provider = repo.get_provider_config(research_provider_id)
    broker_provider = repo.get_provider_config(broker_provider_id)
    configured_mode = repo.get_research_runner_mode()
    env_flag = os.environ.get("TRADEMASTER_ENABLE_REAL_RUNS") == "1"
    explicit_graph_runner = _is_full_tradingagents_graph_runner(resolved_real_runner)
    graph_enabled = explicit_graph_runner or configured_mode == "tradingagents-graph-runner" or env_flag
    runner_mode = (
        "tradingagents-graph-runner"
        if graph_enabled
        else "custom-real-runner"
        if resolved_real_runner is not None
        else "llm-ui-runner"
    )

    graph_provider_unsupported = research_provider.config.get("graph_runner_supported") is False
    provider_unsupported = research_provider.config.get("runner_supported") is False or (
        graph_enabled and graph_provider_unsupported
    )
    return RuntimeStatusResponse(
        research_runner={
            "configured_mode": configured_mode,
            "mode": runner_mode,
            "uses_provider_role": "research_llm",
        },
        research_llm={
            "provider_id": research_provider.provider_id,
            "name": research_provider.name,
            "enabled": research_provider.enabled,
            "status": research_provider.status,
            "secret_ref_configured": research_provider.secret_ref is not None,
            "developer_mode": research_provider.config.get("developer_mode") is True,
            "fallback_expected": not research_provider.enabled
            or provider_unsupported
            or (
                _provider_requires_secret(research_provider.config)
                and research_provider.secret_ref is None
            ),
            "model": research_provider.config.get("model"),
            "base_url": research_provider.config.get("base_url"),
        },
        full_tradingagents_graph={
            "configured": configured_mode == "tradingagents-graph-runner",
            "enabled": graph_enabled,
            "env_flag": env_flag,
        },
        execution_policy={
            "paper_mode_required": policy.paper_mode_required,
            "max_position_percent": policy.max_position_percent,
            "max_sector_percent": policy.max_sector_percent,
            "max_daily_turnover_percent": policy.max_daily_turnover_percent,
            "max_drawdown_percent": policy.max_drawdown_percent,
        },
        broker={
            "provider_id": broker_provider.provider_id,
            "name": broker_provider.name,
            "enabled": broker_provider.enabled,
            "status": broker_provider.status,
            "paper_only": True,
            "approval_required": True,
        },
        developer_mode_enabled=repo.get_developer_mode_enabled(),
    )


def _resolve_research_runner(
    repo: UiRepository,
    resolved_real_runner: RealRunRunner | None,
    *,
    llm_client_factory=None,
) -> RealRunRunner:
    if resolved_real_runner is not None:
        return resolved_real_runner
    if (
        repo.get_research_runner_mode() == "tradingagents-graph-runner"
        or os.environ.get("TRADEMASTER_ENABLE_REAL_RUNS") == "1"
    ):
        from tradingagents.ui.graph_runner import TradingAgentsGraphRunner

        return TradingAgentsGraphRunner(
            provider_config_resolver=lambda: _research_llm_provider_config(repo),
            secret_store_factory=_secret_store_for_ref,
        )
    llm_runner_kwargs = {"llm_client_factory": llm_client_factory} if llm_client_factory else {}
    return LlmResearchRunner(
        repo,
        secret_store_factory=_secret_store_for_ref,
        **llm_runner_kwargs,
    )


def _research_llm_provider_config(repo: UiRepository):
    assignments = repo.list_provider_role_assignments()
    role_provider = {assignment.role_key: assignment.provider_id for assignment in assignments}
    provider_id = str(role_provider.get("research_llm") or "openai-llm")
    return repo.get_provider_config(provider_id)


def _is_full_tradingagents_graph_runner(runner: RealRunRunner | None) -> bool:
    return runner is not None and runner.__class__.__name__ == "TradingAgentsGraphRunner"


def _default_constraint_policy() -> PortfolioConstraintPolicy:
    return PortfolioConstraintPolicy(
        max_position_percent=_env_float("TRADEMASTER_POLICY_MAX_POSITION_PERCENT", 10),
        max_sector_percent=_env_float("TRADEMASTER_POLICY_MAX_SECTOR_PERCENT", 35),
        max_daily_turnover_percent=_env_float("TRADEMASTER_POLICY_MAX_DAILY_TURNOVER_PERCENT", 20),
        max_drawdown_percent=_env_float("TRADEMASTER_POLICY_MAX_DRAWDOWN_PERCENT", 10),
        paper_mode_required=True,
    )


def _default_constraint_context_provider(repo: UiRepository):
    def context_for(run_id: str, symbol: str) -> ConstraintContext:
        config = repo.get_run_config(run_id)
        raw_context = config.get("constraint_context")
        config_context = raw_context if isinstance(raw_context, Mapping) else {}
        symbol_context = config_context.get(symbol.upper())
        scoped_context = symbol_context if isinstance(symbol_context, Mapping) else config_context
        return ConstraintContext(
            account_equity=_context_float(
                scoped_context,
                "account_equity",
                "TRADEMASTER_POLICY_ACCOUNT_EQUITY",
                100_000,
            ),
            current_position_notional=_context_float(
                scoped_context,
                "current_position_notional",
                "TRADEMASTER_POLICY_CURRENT_POSITION_NOTIONAL",
                0,
            ),
            sector_exposure_notional=_context_float(
                scoped_context,
                "sector_exposure_notional",
                "TRADEMASTER_POLICY_SECTOR_EXPOSURE_NOTIONAL",
                0,
            ),
            daily_turnover_notional=_context_float(
                scoped_context,
                "daily_turnover_notional",
                "TRADEMASTER_POLICY_DAILY_TURNOVER_NOTIONAL",
                0,
            ),
            current_drawdown_percent=_context_float(
                scoped_context,
                "current_drawdown_percent",
                "TRADEMASTER_POLICY_CURRENT_DRAWDOWN_PERCENT",
                0,
            ),
        )

    return context_for


def _context_float(
    context: Mapping[str, object],
    key: str,
    env_key: str,
    default: float,
) -> float:
    if key in context:
        return float(context[key])
    return _env_float(env_key, default)


def _env_float(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value in (None, ""):
        return float(default)
    return float(raw_value)


def _alpaca_price_estimator(secret_ref: str):
    def estimate(symbol: str) -> float:
        quote = AlpacaMarketDataProvider(
            secret_store=_secret_store_for_ref(secret_ref),
            secret_ref=secret_ref,
        ).latest_quote(symbol, feed="iex")
        midpoint = (quote.bid_price + quote.ask_price) / 2
        if midpoint <= 0:
            return FakePaperBroker().estimate_price(symbol)
        return midpoint

    return estimate


def _configured_alpaca_broker_base_url(config: Mapping[str, object]) -> str:
    base_url = str(config.get("base_url") or "https://paper-api.alpaca.markets")
    return base_url.removesuffix("/v2").rstrip("/")


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
    if provider_id not in ("plaid-investments", "alpaca-paper-broker", "alpaca-portfolio"):
        raise HTTPException(status_code=404, detail="Portfolio provider not configured")
    try:
        config = repo.get_provider_config(provider_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Portfolio provider not configured") from exc
    if not config.enabled or config.secret_ref is None:
        raise HTTPException(
            status_code=403,
            detail=f"{provider_id} portfolio data is disabled or missing a secret_ref",
        )
    if provider_id == "plaid-investments":
        return PlaidPortfolioProvider(
            secret_store=_secret_store_for_ref(config.secret_ref),
            secret_ref=config.secret_ref,
            http_client=portfolio_http_client,
        )
    # Alpaca portfolio adapter — same secret blob as the broker so users only
    # have to register the alpaca key pair once.
    base_url = "https://paper-api.alpaca.markets"
    if isinstance(config.config, Mapping):
        custom = config.config.get("base_url")
        if isinstance(custom, str) and custom:
            base_url = custom
    return AlpacaPortfolioProvider(
        secret_store=_secret_store_for_ref(config.secret_ref),
        secret_ref=config.secret_ref,
        base_url=base_url,
    )
