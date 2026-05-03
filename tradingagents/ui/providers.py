from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


ProviderRole = Literal["market-data", "portfolio", "brokerage", "llm"]
ProviderStatus = Literal["available", "disabled", "needs_key", "planned"]


class ProviderDescriptor(BaseModel):
    id: str
    name: str
    role: ProviderRole
    status: ProviderStatus
    capabilities: list[str]
    primary_use: str


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
    ),
    ProviderDescriptor(
        id="alpaca-market-data",
        name="Alpaca Market Data",
        role="market-data",
        status="needs_key",
        capabilities=["historical-bars", "minute-bars", "live-quotes", "trade-stream"],
        primary_use="First real market-data source for stocks and ETFs.",
    ),
    ProviderDescriptor(
        id="massive-market-data",
        name="Massive",
        role="market-data",
        status="planned",
        capabilities=["historical-bars", "real-time-bars", "options", "trade-stream"],
        primary_use="Dedicated market-data upgrade path beyond broker-provided feeds.",
    ),
    ProviderDescriptor(
        id="databento-market-data",
        name="Databento",
        role="market-data",
        status="planned",
        capabilities=["tick-history", "live-quotes", "futures", "backtesting"],
        primary_use="Institutional-grade historical and tick data.",
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
    ),
    ProviderDescriptor(
        id="plaid-investments",
        name="Plaid Investments",
        role="portfolio",
        status="needs_key",
        capabilities=["holdings", "securities", "transactions", "account-context"],
        primary_use="Portfolio and account context, not chart candles.",
    ),
    ProviderDescriptor(
        id="fake-paper-broker",
        name="Fake Paper Broker",
        role="brokerage",
        status="available",
        capabilities=["paper-trading", "order-preview", "approval-gate"],
        primary_use="Approval-gated local paper workflow with no real execution.",
    ),
    ProviderDescriptor(
        id="alpaca-paper-broker",
        name="Alpaca Paper Broker",
        role="brokerage",
        status="needs_key",
        capabilities=["paper-trading", "order-preview", "order-submit"],
        primary_use="First real broker adapter, limited to Alpaca paper trading.",
    ),
    ProviderDescriptor(
        id="tradier-broker",
        name="Tradier",
        role="brokerage",
        status="planned",
        capabilities=["paper-trading", "options", "order-submit"],
        primary_use="Future brokerage adapter, especially for options workflows.",
    ),
    ProviderDescriptor(
        id="ibkr-broker",
        name="Interactive Brokers",
        role="brokerage",
        status="planned",
        capabilities=["multi-asset", "order-submit", "account-context"],
        primary_use="Future advanced broker adapter for broader asset coverage.",
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
    ),
    ProviderDescriptor(
        id="openai-llm",
        name="OpenAI",
        role="llm",
        status="available",
        capabilities=["quick-model", "deep-model", "structured-output"],
        primary_use="Default local research LLM configuration.",
    ),
    ProviderDescriptor(
        id="anthropic-llm",
        name="Anthropic",
        role="llm",
        status="needs_key",
        capabilities=["quick-model", "deep-model", "research-reasoning"],
        primary_use="Optional LLM provider for future selectable runs.",
    ),
)


def get_provider_catalog() -> ProviderCatalog:
    return ProviderCatalog(providers=list(PROVIDERS))
