from tradingagents.graph.role_models import (
    ALL_ROLES,
    COORDINATOR_ROLES,
    build_role_model_map,
    resolve_role_model,
)


def test_coordinator_tier_membership():
    assert COORDINATOR_ROLES == {"research_manager", "trader", "portfolio_manager", "research_designer"}
    for role in COORDINATOR_ROLES:
        assert role in ALL_ROLES


def test_resolve_returns_fallback_when_role_models_missing():
    assert resolve_role_model("market_analyst", role_models=None, fallback_model="fb") == "fb"
    assert resolve_role_model("market_analyst", role_models={}, fallback_model="fb") == "fb"


def test_resolve_returns_tier_default_for_coordinator_vs_agent():
    role_models = {"coordinator": "deep", "agent": "quick"}

    assert resolve_role_model("research_manager", role_models=role_models, fallback_model="fb") == "deep"
    assert resolve_role_model("portfolio_manager", role_models=role_models, fallback_model="fb") == "deep"
    assert resolve_role_model("trader", role_models=role_models, fallback_model="fb") == "deep"
    assert resolve_role_model("market_analyst", role_models=role_models, fallback_model="fb") == "quick"
    assert resolve_role_model("bull_researcher", role_models=role_models, fallback_model="fb") == "quick"


def test_per_role_override_wins_over_tier_default():
    role_models = {
        "coordinator": "deep",
        "agent": "quick",
        "overrides": {"portfolio_manager": "boss", "bull_researcher": "stronger"},
    }

    assert resolve_role_model("portfolio_manager", role_models=role_models, fallback_model="fb") == "boss"
    assert resolve_role_model("bull_researcher", role_models=role_models, fallback_model="fb") == "stronger"
    # Unaffected roles still get tier default
    assert resolve_role_model("research_manager", role_models=role_models, fallback_model="fb") == "deep"
    assert resolve_role_model("market_analyst", role_models=role_models, fallback_model="fb") == "quick"


def test_empty_or_missing_tier_default_falls_through_to_fallback():
    # Only an override is set; no coordinator/agent tier values
    role_models = {"overrides": {"trader": "special"}}
    assert resolve_role_model("trader", role_models=role_models, fallback_model="fb") == "special"
    # No override for this role and no tier default -> fallback
    assert resolve_role_model("market_analyst", role_models=role_models, fallback_model="fb") == "fb"


def test_empty_string_tier_default_is_ignored():
    role_models = {"coordinator": "", "agent": "quick"}
    # Empty string for coordinator must not be returned; falls through to fallback
    assert resolve_role_model("research_manager", role_models=role_models, fallback_model="fb") == "fb"
    assert resolve_role_model("market_analyst", role_models=role_models, fallback_model="fb") == "quick"


def test_build_role_model_map_covers_every_canonical_role():
    role_models = {"coordinator": "deep", "agent": "quick"}
    resolved = build_role_model_map(role_models=role_models, fallback_model="fb")

    assert set(resolved.keys()) == set(ALL_ROLES)
    assert resolved["research_manager"] == "deep"
    assert resolved["market_analyst"] == "quick"
    assert resolved["reflector"] == "quick"
    assert resolved["signal_processor"] == "quick"
    assert resolved["research_designer"] == "deep"
    assert resolved["research_extractor"] == "quick"
