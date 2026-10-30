# TradingAgents/graph/setup.py

from typing import Any, Dict
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState

from .conditional_logic import ConditionalLogic
from .role_models import ALL_ROLES, COORDINATOR_ROLES


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any = None,
        deep_thinking_llm: Any = None,
        tool_nodes: Dict[str, ToolNode] | None = None,
        conditional_logic: ConditionalLogic | None = None,
        *,
        role_llms: Dict[str, Any] | None = None,
    ):
        """Initialize with required components.

        Two construction modes are supported:

        * **Per-role mode (preferred):** pass ``role_llms`` as a
          ``{role_key: llm_instance}`` map covering every key in
          ``ALL_ROLES``. Each agent factory gets the LLM bound to its
          own role, so callers can use different models per agent.
        * **Legacy two-LLM mode:** pass ``quick_thinking_llm`` and
          ``deep_thinking_llm`` (positional or keyword). We expand
          that into a per-role map by tier: roles in
          ``COORDINATOR_ROLES`` get ``deep_thinking_llm``; everything
          else gets ``quick_thinking_llm``. This keeps existing CLI
          and test callers working without modification.
        """
        if role_llms is None:
            if quick_thinking_llm is None or deep_thinking_llm is None:
                raise ValueError(
                    "GraphSetup requires either role_llms or both "
                    "quick_thinking_llm and deep_thinking_llm"
                )
            role_llms = {
                role_key: (
                    deep_thinking_llm
                    if role_key in COORDINATOR_ROLES
                    else quick_thinking_llm
                )
                for role_key in ALL_ROLES
            }

        self.role_llms = role_llms
        # Preserve the legacy attribute names for downstream callers
        # (instrumentation, tests) that read them directly.
        self.quick_thinking_llm = quick_thinking_llm or role_llms["market_analyst"]
        self.deep_thinking_llm = deep_thinking_llm or role_llms["research_manager"]
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic

    def setup_graph(
        self, selected_analysts=["market", "social", "news", "fundamentals"]
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst
                - "social": Social media analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
        """
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        # Create analyst nodes
        analyst_nodes = {}
        delete_nodes = {}
        tool_nodes = {}

        if "market" in selected_analysts:
            analyst_nodes["market"] = create_market_analyst(
                self.role_llms["market_analyst"]
            )
            delete_nodes["market"] = create_msg_delete()
            tool_nodes["market"] = self.tool_nodes["market"]

        if "social" in selected_analysts:
            analyst_nodes["social"] = create_social_media_analyst(
                self.role_llms["social_analyst"]
            )
            delete_nodes["social"] = create_msg_delete()
            tool_nodes["social"] = self.tool_nodes["social"]

        if "news" in selected_analysts:
            analyst_nodes["news"] = create_news_analyst(
                self.role_llms["news_analyst"]
            )
            delete_nodes["news"] = create_msg_delete()
            tool_nodes["news"] = self.tool_nodes["news"]

        if "fundamentals" in selected_analysts:
            analyst_nodes["fundamentals"] = create_fundamentals_analyst(
                self.role_llms["fundamentals_analyst"]
            )
            delete_nodes["fundamentals"] = create_msg_delete()
            tool_nodes["fundamentals"] = self.tool_nodes["fundamentals"]

        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(self.role_llms["bull_researcher"])
        bear_researcher_node = create_bear_researcher(self.role_llms["bear_researcher"])
        research_manager_node = create_research_manager(self.role_llms["research_manager"])
        trader_node = create_trader(self.role_llms["trader"])

        # Create risk analysis nodes
        aggressive_analyst = create_aggressive_debator(self.role_llms["aggressive_analyst"])
        neutral_analyst = create_neutral_debator(self.role_llms["neutral_analyst"])
        conservative_analyst = create_conservative_debator(self.role_llms["conservative_analyst"])
        portfolio_manager_node = create_portfolio_manager(self.role_llms["portfolio_manager"])

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add analyst nodes to the graph
        for analyst_type, node in analyst_nodes.items():
            workflow.add_node(f"{analyst_type.capitalize()} Analyst", node)
            workflow.add_node(
                f"Msg Clear {analyst_type.capitalize()}", delete_nodes[analyst_type]
            )
            workflow.add_node(f"tools_{analyst_type}", tool_nodes[analyst_type])

        # Add other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)

        # Define edges
        # Start with the first analyst
        first_analyst = selected_analysts[0]
        workflow.add_edge(START, f"{first_analyst.capitalize()} Analyst")

        # Connect analysts in sequence
        for i, analyst_type in enumerate(selected_analysts):
            current_analyst = f"{analyst_type.capitalize()} Analyst"
            current_tools = f"tools_{analyst_type}"
            current_clear = f"Msg Clear {analyst_type.capitalize()}"

            # Add conditional edges for current analyst
            workflow.add_conditional_edges(
                current_analyst,
                getattr(self.conditional_logic, f"should_continue_{analyst_type}"),
                [current_tools, current_clear],
            )
            workflow.add_edge(current_tools, current_analyst)

            # Connect to next analyst or to Bull Researcher if this is the last analyst
            if i < len(selected_analysts) - 1:
                next_analyst = f"{selected_analysts[i+1].capitalize()} Analyst"
                workflow.add_edge(current_clear, next_analyst)
            else:
                workflow.add_edge(current_clear, "Bull Researcher")

        # Add remaining edges
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bull Researcher": "Bull Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Conservative Analyst": "Conservative Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Neutral Analyst": "Neutral Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Aggressive Analyst": "Aggressive Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )

        workflow.add_edge("Portfolio Manager", END)

        return workflow
