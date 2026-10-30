from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


ProviderRole = Literal["market-data", "portfolio", "brokerage", "llm", "observability", "safety"]
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


class ProviderRoleDefault(BaseModel):
    role_key: str
    provider_id: str
    surface: ProviderControlSurface


PROVIDERS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        id="simulated-market-data",
        name="Simulated Market Data",
        role="market-data",
        status="disabled",
        capabilities=["historical-bars", "delayed-bars", "quotes", "volume", "vwap"],
        primary_use="Internal test fixture only. Disabled for the live local product.",
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
        status="disabled",
        capabilities=["paper-trading", "order-preview", "approval-gate"],
        primary_use="Internal test fixture only. Disabled for the live local product.",
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
        id="openai-codex-oauth-llm",
        name="OpenAI Codex (ChatGPT OAuth)",
        role="llm",
        status="available",
        capabilities=[
            "developer-mode",
            "codex-oauth",
            "responses-api",
            "tool-calling",
            "streaming",
        ],
        primary_use=(
            "Routes through chatgpt.com/backend-api/codex using the local "
            "`codex login` session. Full Responses-API support including "
            "tool calling and structured output; usable for every LLM role "
            "in the graph runner."
        ),
        control_surface="platform",
        write_authority="none",
    ),
    ProviderDescriptor(
        id="github-copilot-oauth-llm",
        name="GitHub Copilot OAuth",
        role="llm",
        status="available",
        capabilities=[
            "github-oauth",
            "copilot-business",
            "openai-compatible",
            "tool-calling",
            "structured-output",
        ],
        primary_use=(
            "Routes the research committee through the user's GitHub Copilot "
            "Business subscription via the local OAuth session. OpenAI-shaped "
            "Chat Completions (gpt-4o / gpt-4o-mini) with tool calling and "
            "structured output; not used for broker-facing execution."
        ),
        control_surface="platform",
        write_authority="none",
    ),
    ProviderDescriptor(
        id="kimi-coder-llm",
        name="Kimi for Coding (Moonshot OAuth)",
        role="llm",
        status="available",
        capabilities=[
            "kimi-oauth",
            "anthropic-messages",
            "reasoning-model",
            "deep-analysis",
        ],
        primary_use=(
            "Routes through api.kimi.com/coding using the local Kimi OAuth "
            "session (cliproxy kimi-login). Anthropic-Messages-shaped "
            "completions with kimi-k2-thinking, a reasoning model best "
            "suited to deep-analysis roles; wasteful for quick screening. "
            "Assignable from Settings; not wired to any role by default."
        ),
        control_surface="platform",
        write_authority="none",
    ),
    ProviderDescriptor(
        id="lm-studio-llm",
        name="LM Studio",
        role="llm",
        status="available",
        capabilities=["openai-compatible", "local-model", "structured-output"],
        primary_use="Local OpenAI-compatible research LLM endpoint for offline agent tests.",
        control_surface="ai-harness",
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
        id="mistral-medium-execution-llm",
        name="Mistral Medium 3.5",
        role="llm",
        status="planned",
        capabilities=["deterministic-execution", "structured-output", "openrouter"],
        primary_use="Planned execution-agent LLM for strict broker-adjacent reasoning.",
        control_surface="ai-harness",
        write_authority="none",
    ),
    ProviderDescriptor(
        id="pyreason-circuit-breaker",
        name="PyReason Circuit Breaker",
        role="safety",
        status="planned",
        capabilities=["temporal-rules", "crash-halt", "drawdown-guard", "explainable-policy"],
        primary_use="Planned symbolic safety provider for execution-agent circuit breakers.",
        control_surface="ai-harness",
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

DEFAULT_PROVIDER_ROLE_ASSIGNMENTS: tuple[ProviderRoleDefault, ...] = (
    ProviderRoleDefault(role_key="research_llm", provider_id="lm-studio-llm", surface="ai-harness"),
    ProviderRoleDefault(role_key="research_designer", provider_id="lm-studio-llm", surface="ai-harness"),
    ProviderRoleDefault(role_key="research_extractor", provider_id="lm-studio-llm", surface="ai-harness"),
    ProviderRoleDefault(role_key="execution_llm", provider_id="mistral-medium-execution-llm", surface="ai-harness"),
    ProviderRoleDefault(role_key="market_data", provider_id="alpaca-market-data", surface="agent-data"),
    ProviderRoleDefault(role_key="broker", provider_id="alpaca-paper-broker", surface="ai-harness"),
    ProviderRoleDefault(role_key="portfolio", provider_id="plaid-investments", surface="agent-data"),
    ProviderRoleDefault(role_key="observability", provider_id="langfuse-observability", surface="platform"),
    ProviderRoleDefault(role_key="safety", provider_id="pyreason-circuit-breaker", surface="ai-harness"),
)

DEFAULT_PROVIDER_CONFIGS: dict[str, dict[str, object]] = {
    "openai-codex-oauth-llm": {
        "config_version": 4,
        "auth_required": False,
        "auth_type": "codex-oauth",
        "provider": "codex-oauth",
        "model": "gpt-5.4-mini",
        "quick_model": "gpt-5.4-mini",
        "deep_model": "gpt-5.4",
        "role_models": {
            "coordinator": "gpt-5.4",
            "agent": "gpt-5.4-mini",
            "overrides": {},
        },
        "timeout": 120,
        "developer_mode": True,
        "runner_supported": True,
        "graph_runner_supported": True,
    },
    "github-copilot-oauth-llm": {
        "config_version": 2,
        "auth_required": False,
        "auth_type": "github-copilot-oauth",
        "provider": "github-copilot-oauth",
        "model": "gpt-4o",
        "quick_model": "gpt-4o-mini",
        "deep_model": "gpt-4o",
        "role_models": {
            "coordinator": "gpt-4o",
            "agent": "gpt-4o-mini",
            "overrides": {},
        },
        "oauth_file": "~/.config/github-copilot/trademaster-oauth.json",
        "timeout": 120,
        "runner_supported": True,
        "graph_runner_supported": True,
    },
    "kimi-coder-llm": {
        "config_version": 1,
        "auth_required": False,
        "auth_type": "kimi-oauth",
        "provider": "kimi-oauth",
        "model": "kimi-k2-thinking",
        "quick_model": "kimi-k2-thinking",
        "deep_model": "kimi-k2-thinking",
        "role_models": {
            "coordinator": "kimi-k2-thinking",
            "agent": "kimi-k2-thinking",
            "overrides": {},
        },
        "auth_dir": "~/.ccs/cliproxy/auth",
        "timeout": 300,
        "runner_supported": True,
        "graph_runner_supported": True,
    },
    "lm-studio-llm": {
        "auth_required": False,
        "base_url": "http://127.0.0.1:1234/v1",
        "model": "local-model",
        "provider": "openai-compatible",
        "timeout": 60,
        "disable_structured_output": True,
    },
}


def get_provider_catalog() -> ProviderCatalog:
    return ProviderCatalog(providers=list(PROVIDERS))


def provider_descriptor_by_id(provider_id: str) -> ProviderDescriptor | None:
    return next((provider for provider in PROVIDERS if provider.id == provider_id), None)


def default_provider_config(provider_id: str) -> dict[str, object]:
    return dict(DEFAULT_PROVIDER_CONFIGS.get(provider_id, {}))
