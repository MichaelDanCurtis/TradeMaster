"""Per-role model resolution for the TradingAgents graph.

Today the graph wires every analyst, researcher, trader, risk debator,
and the portfolio manager to one of two shared LLM instances
(``quick_thinking_llm`` for everything except ``Research Manager`` and
``Portfolio Manager``, which use ``deep_thinking_llm``). That coarse
split is enough for a demo but doesn't let the operator say "use a
stronger model for the Portfolio Manager only" or "let Bull/Bear debate
on a different model than the analysts".

This module defines the canonical role keys and resolves
``role_key -> model_name`` using a three-layer inheritance rule:

    1. Per-role override (most specific)
    2. Tier default (``coordinator`` or ``agent``)
    3. Provider's base ``model`` field (least specific, fallback)

Coordinator-tier roles are the synthesis/decision points -- Research
Manager folds bull/bear debate into a thesis, Trader packages the order
flow even when a quant model picks the trade, Portfolio Manager renders
the final decision. Every other role is "agent-tier".

Cross-provider per role is intentionally NOT supported here: the input
is a single model-name string per role. Wiring different roles to
different providers is a separate concern handled by future work in the
provider registry layer.
"""

from __future__ import annotations

from typing import Any


# Coordinator-tier roles get the higher-capability default model.
# Trader is here even though we'll eventually delegate the actual
# trade decision to a non-LLM model: the LLM still orchestrates the
# handoff to risk analysts and packages the order context.
COORDINATOR_ROLES: frozenset[str] = frozenset(
    {"research_manager", "trader", "portfolio_manager", "research_designer"}
)


# Canonical role keys used by GraphSetup and the agent factories.
# Ordered for readable iteration; the set membership in
# ``COORDINATOR_ROLES`` is what determines tier, not list position.
ALL_ROLES: tuple[str, ...] = (
    "market_analyst",
    "social_analyst",
    "news_analyst",
    "fundamentals_analyst",
    "bull_researcher",
    "bear_researcher",
    "research_manager",
    "trader",
    "aggressive_analyst",
    "neutral_analyst",
    "conservative_analyst",
    "portfolio_manager",
    "reflector",
    "signal_processor",
    "research_designer",
    "research_extractor",
)


def resolve_role_model(
    role_key: str,
    *,
    role_models: dict[str, Any] | None,
    fallback_model: str,
) -> str:
    """Resolve which model name a given role should use.

    Lookup order:

    1. ``role_models["overrides"][role_key]`` -- per-role override.
    2. ``role_models["coordinator"]`` if the role is in
       ``COORDINATOR_ROLES``, else ``role_models["agent"]``.
    3. ``fallback_model`` -- typically the provider's ``model`` field,
       used when ``role_models`` is missing or has no tier default.

    ``role_models`` may be ``None`` or an empty dict, in which case
    every role resolves to ``fallback_model`` directly. This keeps the
    legacy single-model configs working with zero migration work.
    """
    if role_models:
        overrides = role_models.get("overrides") or {}
        override = overrides.get(role_key)
        if isinstance(override, str) and override:
            return override

        tier = "coordinator" if role_key in COORDINATOR_ROLES else "agent"
        tier_default = role_models.get(tier)
        if isinstance(tier_default, str) and tier_default:
            return tier_default

    return fallback_model


def build_role_model_map(
    *,
    role_models: dict[str, Any] | None,
    fallback_model: str,
) -> dict[str, str]:
    """Resolve all canonical roles up-front into ``{role_key: model}``.

    Convenient when the caller wants to pre-build all the LLM clients
    in a single pass rather than calling ``resolve_role_model`` per
    role on demand. Roles that resolve to the same model name can then
    be deduplicated by the caller to avoid building redundant clients.
    """
    return {
        role_key: resolve_role_model(
            role_key,
            role_models=role_models,
            fallback_model=fallback_model,
        )
        for role_key in ALL_ROLES
    }
