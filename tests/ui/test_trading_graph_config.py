from copy import deepcopy
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph import trading_graph
from tradingagents.graph.role_models import COORDINATOR_ROLES


class _FakeMemoryLog:
    def __init__(self, config):
        pass


class _FakeWorkflow:
    def compile(self, *args, **kwargs):
        return object()


class _FakeGraphSetup:
    last_kwargs: dict = {}

    def __init__(self, *args, **kwargs):
        _FakeGraphSetup.last_kwargs = kwargs

    def setup_graph(self, selected_analysts):
        return _FakeWorkflow()


def _install_graph_stubs(monkeypatch, *, llm_client_factory):
    monkeypatch.setattr(trading_graph, "create_llm_client", llm_client_factory)
    monkeypatch.setattr(trading_graph, "set_config", lambda config: None)
    monkeypatch.setattr(trading_graph, "TradingMemoryLog", _FakeMemoryLog)
    monkeypatch.setattr(trading_graph, "GraphSetup", _FakeGraphSetup)
    monkeypatch.setattr(trading_graph, "Propagator", lambda max_recur_limit=100: None)
    monkeypatch.setattr(
        trading_graph.TradingAgentsGraph,
        "_create_tool_nodes",
        lambda self: {},
    )


def test_trading_graph_passes_configured_recursion_limit_to_propagator(
    monkeypatch, tmp_path: Path
):
    captured = {}

    class FakeLlmClient:
        def get_llm(self):
            return object()

    monkeypatch.setattr(trading_graph, "create_llm_client", lambda **kwargs: FakeLlmClient())
    monkeypatch.setattr(trading_graph, "set_config", lambda config: None)
    monkeypatch.setattr(trading_graph, "TradingMemoryLog", _FakeMemoryLog)
    monkeypatch.setattr(trading_graph, "GraphSetup", _FakeGraphSetup)

    class FakePropagator:
        def __init__(self, max_recur_limit=100):
            captured["max_recur_limit"] = max_recur_limit

    monkeypatch.setattr(trading_graph, "Propagator", FakePropagator)
    monkeypatch.setattr(
        trading_graph.TradingAgentsGraph,
        "_create_tool_nodes",
        lambda self: {},
    )

    config = deepcopy(DEFAULT_CONFIG)
    config.update(
        {
            "data_cache_dir": str(tmp_path / "cache"),
            "results_dir": str(tmp_path / "results"),
            "max_recur_limit": 321,
        }
    )

    trading_graph.TradingAgentsGraph(config=config)

    assert captured["max_recur_limit"] == 321


def test_trading_graph_builds_distinct_llms_per_role_from_role_models(
    monkeypatch, tmp_path: Path
):
    """When ``role_models`` is set, distinct model names build distinct
    LLM clients and roles share the same LLM iff they resolve to the
    same model. Verifies the dedup-by-model_name behaviour in
    ``TradingAgentsGraph.__init__``.
    """
    constructed_models: list[str] = []

    class FakeLlmClient:
        def __init__(self, model):
            self._model = model
            self._llm = object()

        def get_llm(self):
            return self._llm

    def fake_factory(*, provider, model, base_url=None, **kwargs):
        constructed_models.append(model)
        return FakeLlmClient(model)

    _install_graph_stubs(monkeypatch, llm_client_factory=fake_factory)

    config = deepcopy(DEFAULT_CONFIG)
    config.update(
        {
            "data_cache_dir": str(tmp_path / "cache"),
            "results_dir": str(tmp_path / "results"),
            "llm_provider": "codex-oauth",
            "model": "gpt-5.4-mini",
            "role_models": {
                "coordinator": "gpt-5.4",
                "agent": "gpt-5.4-mini",
                "overrides": {"portfolio_manager": "gpt-5.5"},
            },
        }
    )

    graph = trading_graph.TradingAgentsGraph(config=config)

    # Three distinct model names -> three client constructions
    assert sorted(constructed_models) == ["gpt-5.4", "gpt-5.4-mini", "gpt-5.5"]
    # Coordinator roles share the coordinator LLM (except the
    # portfolio_manager override, which has its own)
    research_manager_llm = graph.role_llms["research_manager"]
    trader_llm = graph.role_llms["trader"]
    assert research_manager_llm is trader_llm
    assert graph.role_llms["portfolio_manager"] is not research_manager_llm
    # Agent-tier roles share the agent LLM
    assert graph.role_llms["market_analyst"] is graph.role_llms["bull_researcher"]
    # Coordinator vs agent are different
    assert research_manager_llm is not graph.role_llms["market_analyst"]
    # Legacy accessors still point at sensible LLMs
    assert graph.deep_thinking_llm is research_manager_llm
    assert graph.quick_thinking_llm is graph.role_llms["market_analyst"]


def test_trading_graph_falls_back_to_quick_deep_when_no_role_models(
    monkeypatch, tmp_path: Path
):
    """Configs using the legacy ``quick_think_llm`` / ``deep_think_llm``
    keys (no ``role_models``) must still produce two distinct LLMs
    split along the coordinator/agent tier.
    """
    constructed_models: list[str] = []

    class FakeLlmClient:
        def __init__(self, model):
            self._llm = object()

        def get_llm(self):
            return self._llm

    def fake_factory(*, provider, model, base_url=None, **kwargs):
        constructed_models.append(model)
        return FakeLlmClient(model)

    _install_graph_stubs(monkeypatch, llm_client_factory=fake_factory)

    config = deepcopy(DEFAULT_CONFIG)
    config.update(
        {
            "data_cache_dir": str(tmp_path / "cache"),
            "results_dir": str(tmp_path / "results"),
            "llm_provider": "openai",
            "quick_think_llm": "model-quick",
            "deep_think_llm": "model-deep",
        }
    )
    config.pop("role_models", None)

    graph = trading_graph.TradingAgentsGraph(config=config)

    assert sorted(constructed_models) == ["model-deep", "model-quick"]
    for role in COORDINATOR_ROLES:
        assert graph.role_llms[role] is graph.deep_thinking_llm
    assert graph.role_llms["market_analyst"] is graph.quick_thinking_llm
