from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


ProviderRole = Literal["market-data", "portfolio", "brokerage", "llm", "observability"]
ProviderStatus = Literal["available", "disabled", "needs_key", "planned"]
ProviderControlSurface = Literal["agent-data", "human-cockpit", "ai-harness", "platform"]
ProviderWriteAuthority = Literal["none", "read-only", "paper-trading", "live-trading"]


class ProviderDescriptor(BaseModel):
    id: str
    name: str
    role: ProviderRole
    status: ProviderStatus
    capabilities: list[str]
    primary_use: str
    control_surface: ProviderControlSurface = "platform"
    write_authority: ProviderWriteAuthority = "none"


class ProviderConfig(BaseModel):
    provider_id: str
    name: str
    role: ProviderRole
    status: ProviderStatus
    capabilities: list[str]
    primary_use: str
    control_surface: ProviderControlSurface
    write_authority: ProviderWriteAuthority
    enabled: bool
    secret_ref: str | None = None
    config: dict[str, object]
    health: dict[str, object]


class ProviderCatalog(BaseModel):
    providers: list[ProviderDescriptor]


PROVIDERS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        id="simulated-market-data",
        name="Simulated Market Data",
        role="market-data",
        status="available",
        capabilities=["historical-bars", "delayed-bars", "quotes", "volume", "vwap"],
        primary_use="Local deterministic bars for UI work, demos, and tests.",
        control_surface="agent-data",
        write_authority="none",
    ),
    ProviderDescriptor(
        id="alpaca-market-data",
        name="Alpaca Market Data",
        role="market-data",
        status="needs_key",
        capabilities=["historical-bars", "minute-bars", "live-quotes", "trade-stream"],
        primary_use="First real market-data source for stocks and ETFs.",
        control_surface="agent-data",
        write_authority="read-only",
    ),
    ProviderDescriptor(
        id="massive-market-data",
        name="Massive",
        role="market-data",
        status="planned",
        capabilities=["historical-bars", "real-time-bars", "options", "trade-stream"],
        primary_use="Dedicated market-data upgrade path beyond broker-provided feeds.",
        control_surface="agent-data",
        write_authority="read-only",
    ),
    ProviderDescriptor(
        id="databento-market-data",
        name="Databento",
        role="market-data",
        status="planned",
        capabilities=["tick-history", "live-quotes", "futures", "backtesting"],
        primary_use="Institutional-grade historical and tick data.",
        control_surface="agent-data",
        write_authority="read-only",
    ),
    ProviderDescriptor(
        id="webull-market-data",
        name="Webull Market Data",
        role="market-data",
        status="planned",
        capabilities=[
            "historical-bars",
            "snapshot-quotes",
            "real-time-streaming",
            "crypto",
        ],
        primary_use=(
            "Primary trading-surface data adapter for Webull-backed market context."
        ),
        control_surface="human-cockpit",
        write_authority="read-only",
    ),
    ProviderDescriptor(
        id="plaid-investments",
        name="Plaid Investments",
        role="portfolio",
        status="needs_key",
        capabilities=["banking", "balances", "holdings", "securities", "transactions", "account-context"],
        primary_use="Read-only banking, balances, holdings, transactions, and account context.",
        control_surface="agent-data",
        write_authority="read-only",
    ),
    ProviderDescriptor(
        id="fake-paper-broker",
        name="Fake Paper Broker",
        role="brokerage",
        status="available",
        capabilities=["paper-trading", "order-preview", "approval-gate"],
        primary_use="Approval-gated local paper workflow with no real execution.",
        control_surface="ai-harness",
        write_authority="paper-trading",
    ),
    ProviderDescriptor(
        id="alpaca-paper-broker",
        name="Alpaca Paper Broker",
        role="brokerage",
        status="needs_key",
        capabilities=["paper-trading", "order-preview", "order-submit"],
        primary_use="First real broker adapter, limited to Alpaca paper trading.",
        control_surface="ai-harness",
        write_authority="paper-trading",
    ),
    ProviderDescriptor(
        id="tradier-broker",
        name="Tradier",
        role="brokerage",
        status="planned",
        capabilities=["paper-trading", "options", "order-submit"],
        primary_use="Future brokerage adapter, especially for options workflows.",
        control_surface="ai-harness",
        write_authority="paper-trading",
    ),
    ProviderDescriptor(
        id="ibkr-broker",
        name="Interactive Brokers",
        role="brokerage",
        status="planned",
        capabilities=["multi-asset", "order-submit", "account-context"],
        primary_use="Future advanced broker adapter for broader asset coverage.",
        control_surface="ai-harness",
        write_authority="live-trading",
    ),
    ProviderDescriptor(
        id="webull-broker",
        name="Webull Broker",
        role="brokerage",
        status="planned",
        capabilities=["account-context", "order-preview", "order-submit"],
        primary_use=(
            "Future Webull account and order adapter, disabled until approval "
            "policies and API credentials are configured."
        ),
        control_surface="human-cockpit",
        write_authority="live-trading",
    ),
    ProviderDescriptor(
        id="openai-llm",
        name="OpenAI",
        role="llm",
        status="available",
        capabilities=["quick-model", "deep-model", "structured-output"],
        primary_use="Default local research LLM configuration.",
        control_surface="platform",
        write_authority="none",
    ),
    ProviderDescriptor(
        id="anthropic-llm",
        name="Anthropic",
        role="llm",
        status="needs_key",
        capabilities=["quick-model", "deep-model", "research-reasoning"],
        primary_use="Optional LLM provider for future selectable runs.",
        control_surface="platform",
        write_authority="none",
    ),
    ProviderDescriptor(
        id="langfuse-observability",
        name="LangFuse",
        role="observability",
        status="needs_key",
        capabilities=["trace-export", "cost-metadata", "run-correlation"],
        primary_use="External observability for LangGraph and TradeMaster run traces.",
        control_surface="platform",
        write_authority="none",
    ),
)


def get_provider_catalog() -> ProviderCatalog:
    return ProviderCatalog(providers=list(PROVIDERS))


def provider_descriptor_by_id(provider_id: str) -> ProviderDescriptor | None:
    return next((provider for provider in PROVIDERS if provider.id == provider_id), None)
