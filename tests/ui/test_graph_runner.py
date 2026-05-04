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
    assert captured["company_name"] == "NVDA"
    assert captured["trade_date"] == "2026-04-30"
    assert [event.type for event in result.events] == [
        "agent.started",
        "report.updated",
        "agent.started",
        "report.updated",
        "decision.created",
    ]
    assert result.action == "Hold"
    assert result.thesis == "Hold until the setup improves."
