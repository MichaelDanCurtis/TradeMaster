from types import SimpleNamespace

import pytest

from tradingagents.ui.events import RunConfig
from tradingagents.ui.graph_runner import TradingAgentsGraphRunner


def test_graph_runner_maps_run_config_and_final_state_to_ui_events():
    captured = {}

    class FakeGraph:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def propagate(self, company_name: str, trade_date: str):
            captured["company_name"] = company_name
            captured["trade_date"] = trade_date
            return (
                {
                    "market_report": "Market report body.",
                    "news_report": "News report body.",
                    "final_trade_decision": "Hold until the setup improves.",
                },
                "Hold",
            )

    runner = TradingAgentsGraphRunner(graph_factory=FakeGraph, config_template={})

    result = runner(
        "run_123",
        RunConfig(
            ticker="nvda",
            trade_date="2026-04-30",
            analysts=["market", "news"],
            research_depth=3,
            llm_provider="anthropic",
            quick_model="claude-haiku",
            deep_model="claude-sonnet",
            checkpoint=True,
            execution_mode="real",
        ),
    )

    assert captured["selected_analysts"] == ["market", "news"]
    assert captured["debug"] is False
    assert captured["config"]["llm_provider"] == "anthropic"
    assert captured["config"]["quick_think_llm"] == "claude-haiku"
    assert captured["config"]["deep_think_llm"] == "claude-sonnet"
    assert captured["config"]["checkpoint_enabled"] is True
    assert captured["config"]["max_debate_rounds"] == 3
    assert captured["config"]["max_risk_discuss_rounds"] == 3
    assert captured["config"]["max_recur_limit"] == 410
    assert captured["company_name"] == "NVDA"
    assert captured["trade_date"] == "2026-04-30"
    assert [event.type for event in result.events] == [
        "agent.started",
        "report.updated",
        "agent.started",
        "report.updated",
        "agent.started",
        "report.updated",
        "decision.created",
    ]
    assert result.action == "Hold"
    assert result.thesis == "Hold until the setup improves."


def test_graph_runner_exposes_full_tradingagents_hierarchy_as_reports():
    class FakeGraph:
        def __init__(self, **kwargs):
            pass

        def propagate(self, company_name: str, trade_date: str):
            return (
                {
                    "market_report": "Market report.",
                    "sentiment_report": "Social report.",
                    "news_report": "News report.",
                    "fundamentals_report": "Fundamentals report.",
                    "investment_debate_state": {
                        "bull_history": "Bull case.",
                        "bear_history": "Bear case.",
                        "judge_decision": "Research manager synthesis.",
                    },
                    "investment_plan": "Research manager plan.",
                    "trader_investment_plan": "Trader execution plan.",
                    "risk_debate_state": {
                        "current_aggressive_response": "Aggressive risk stance.",
                        "current_conservative_response": "Conservative risk stance.",
                        "current_neutral_response": "Neutral risk stance.",
                        "judge_decision": "Portfolio risk synthesis.",
                    },
                    "final_trade_decision": "**Rating**: Overweight\nContinue research before execution.",
                },
                "Overweight",
            )

    runner = TradingAgentsGraphRunner(graph_factory=FakeGraph, config_template={})

    result = runner(
        "run_456",
        RunConfig(
            ticker="NVDA",
            trade_date="2026-04-30",
            analysts=["market", "social", "news", "fundamentals"],
            execution_mode="real",
        ),
    )
    report_events = [event for event in result.events if event.type == "report.updated"]
    by_node = {event.node: event.payload["report"] for event in report_events}

    assert by_node["Market Analyst"] == "Market report."
    assert by_node["Bull Researcher"] == "Bull case."
    assert by_node["Bear Researcher"] == "Bear case."
    assert by_node["Research Manager"] == "Research manager synthesis."
    assert by_node["Trader"] == "Trader execution plan."
    assert by_node["Aggressive Analyst"] == "Aggressive risk stance."
    assert by_node["Conservative Analyst"] == "Conservative risk stance."
    assert by_node["Neutral Analyst"] == "Neutral risk stance."
    assert by_node["Portfolio Manager"] == "**Rating**: Overweight\nContinue research before execution."
    assert result.rating == "Overweight"
    assert result.action == "Buy"


def test_graph_runner_uses_provider_registry_config_for_llm_models():
    captured = {}

    class FakeGraph:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def propagate(self, company_name: str, trade_date: str):
            return ({"final_trade_decision": "**Rating**: Hold\nWait."}, "Hold")

    provider_config = SimpleNamespace(
        config={
            "provider": "openai-compatible",
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "local-qwen",
            "auth_required": False,
        },
        secret_ref=None,
    )
    runner = TradingAgentsGraphRunner(
        graph_factory=FakeGraph,
        config_template={},
        provider_config_resolver=lambda: provider_config,
    )

    runner("run_789", RunConfig(ticker="NVDA", trade_date="2026-04-30", execution_mode="real"))

    assert captured["config"]["llm_provider"] == "openai-compatible"
    assert captured["config"]["backend_url"] == "http://127.0.0.1:1234/v1"
    assert captured["config"]["quick_think_llm"] == "local-qwen"
    assert captured["config"]["deep_think_llm"] == "local-qwen"
    assert captured["config"]["api_key"] == "local-no-auth"


def test_graph_runner_forwards_role_models_when_present_in_provider_config():
    captured = {}

    class FakeGraph:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def propagate(self, company_name: str, trade_date: str):
            return ({"final_trade_decision": "**Rating**: Hold\nWait."}, "Hold")

    role_models = {
        "coordinator": "gpt-5.4",
        "agent": "gpt-5.4-mini",
        "overrides": {"portfolio_manager": "gpt-5.5"},
    }
    provider_config = SimpleNamespace(
        config={
            "provider": "codex-oauth",
            "model": "gpt-5.4-mini",
            "auth_required": False,
            "role_models": role_models,
        },
        secret_ref=None,
    )
    runner = TradingAgentsGraphRunner(
        graph_factory=FakeGraph,
        config_template={},
        provider_config_resolver=lambda: provider_config,
    )

    runner("run_role_models", RunConfig(ticker="NVDA", trade_date="2026-04-30", execution_mode="real"))

    assert captured["config"]["role_models"] == role_models


def test_graph_runner_omits_role_models_when_provider_config_has_none():
    captured = {}

    class FakeGraph:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def propagate(self, company_name: str, trade_date: str):
            return ({"final_trade_decision": "**Rating**: Hold\nWait."}, "Hold")

    provider_config = SimpleNamespace(
        config={
            "provider": "openai-compatible",
            "model": "local-qwen",
            "auth_required": False,
        },
        secret_ref=None,
    )
    runner = TradingAgentsGraphRunner(
        graph_factory=FakeGraph,
        config_template={},
        provider_config_resolver=lambda: provider_config,
    )

    runner("run_no_role_models", RunConfig(ticker="NVDA", trade_date="2026-04-30", execution_mode="real"))

    assert "role_models" not in captured["config"]


def test_graph_runner_allows_provider_registry_to_override_recursion_limit():
    captured = {}

    class FakeGraph:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def propagate(self, company_name: str, trade_date: str):
            return ({"final_trade_decision": "**Rating**: Hold\nWait."}, "Hold")

    provider_config = SimpleNamespace(
        config={
            "provider": "openai-compatible",
            "model": "local-qwen",
            "auth_required": False,
            "max_recur_limit": 275,
        },
        secret_ref=None,
    )
    runner = TradingAgentsGraphRunner(
        graph_factory=FakeGraph,
        config_template={},
        provider_config_resolver=lambda: provider_config,
    )

    runner("run_789", RunConfig(ticker="NVDA", trade_date="2026-04-30", execution_mode="real"))

    assert captured["config"]["max_recur_limit"] == 275


def test_graph_runner_passes_provider_structured_output_disable_flag():
    captured = {}

    class FakeGraph:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def propagate(self, company_name: str, trade_date: str):
            return ({"final_trade_decision": "**Rating**: Hold\nWait."}, "Hold")

    provider_config = SimpleNamespace(
        config={
            "provider": "openai-compatible",
            "model": "local-qwen",
            "auth_required": False,
            "disable_structured_output": True,
        },
        secret_ref=None,
    )
    runner = TradingAgentsGraphRunner(
        graph_factory=FakeGraph,
        config_template={},
        provider_config_resolver=lambda: provider_config,
    )

    runner("run_local", RunConfig(ticker="NVDA", trade_date="2026-04-30", execution_mode="real"))

    assert captured["config"]["disable_structured_output"] is True


def test_graph_runner_rejects_unsupported_oauth_provider_before_running_graph():
    provider_config = SimpleNamespace(
        provider_id="github-copilot-oauth-llm",
        config={"provider": "github-copilot-oauth", "runner_supported": False},
        secret_ref="keychain:github:oauth",
    )
    runner = TradingAgentsGraphRunner(
        graph_factory=lambda **kwargs: None,
        config_template={},
        provider_config_resolver=lambda: provider_config,
    )

    with pytest.raises(RuntimeError, match="does not have a graph runner adapter"):
        runner("run_unsupported", RunConfig(ticker="NVDA", trade_date="2026-04-30", execution_mode="real"))
