import pytest

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig
from tradingagents.ui.llm_runner import (
    LlmResearchRunner,
    _analyst_events,
    _confidence_value,
    _decision_path_events,
    _debate_events,
    _extract_json_payload,
    _fallback_decision,
    _research_prompt,
)
from tradingagents.ui.repository import UiRepository


def test_extract_json_payload_accepts_surrounded_local_model_output():
    payload = _extract_json_payload(
        'Here is the JSON:\n{"rating":"Neutral","action":"Hold","confidence":0.5}\nDone.'
    )

    assert payload["rating"] == "Neutral"
    assert payload["action"] == "Hold"


def test_extract_json_payload_accepts_fenced_json():
    payload = _extract_json_payload(
        '```json\n{"rating":"Overweight","action":"Buy","confidence":0.7}\n```'
    )

    assert payload["rating"] == "Overweight"
    assert payload["action"] == "Buy"


def test_extract_json_payload_rejects_non_json_text():
    with pytest.raises(ValueError):
        _extract_json_payload("I would hold this stock.")


def test_extract_json_payload_recovers_required_fields_from_near_json():
    payload = _extract_json_payload(
        '{\n'
        '  "rating": "Buy",\n'
        '  "action": "Buy",\n'
        '  "thesis": "Strong setup."",\n'
        '  "risk_notes": "Review sizing.",\n'
        '  "confidence": "Moderate to High",\n'
        '  "extra": {"ignored": true}\n'
        '}'
    )

    assert payload["rating"] == "Buy"
    assert payload["action"] == "Buy"
    assert payload["thesis"] == "Strong setup."
    assert payload["confidence"] == "Moderate to High"


def test_confidence_value_normalizes_local_model_words():
    assert _confidence_value("Moderate to High") == 0.75
    assert _confidence_value("medium") == 0.55
    assert _confidence_value("low") == 0.3
    assert _confidence_value(1.4) == 1.0


def test_llm_runner_emits_full_tradingagents_research_path():
    config = RunConfig(ticker="NVDA", trade_date="2026-05-06", execution_mode="real")
    decision = _fallback_decision(config, reason="test")

    events = [
        *_debate_events("run_123", config),
        *_decision_path_events("run_123", decision, fallback=True),
    ]

    assert [event.node for event in events] == [
        "Bull Researcher",
        "Bull Researcher",
        "Bear Researcher",
        "Bear Researcher",
        "Research Manager",
        "Trader",
        "Trader",
        "Risk Manager",
        "Risk Manager",
    ]
    assert events[0].type == "agent.started"
    assert events[-1].payload["section"] == "risk_review"


def test_llm_runner_report_updates_include_readable_agent_report_text():
    config = RunConfig(ticker="NVDA", trade_date="2026-05-06", execution_mode="real")
    decision = _fallback_decision(config, reason="test")

    events = [
        *_debate_events("run_123", config),
        *_decision_path_events("run_123", decision, fallback=True),
    ]
    reports = [event for event in events if event.type == "report.updated"]

    assert reports
    assert all(isinstance(event.payload.get("report"), str) for event in reports)
    assert any("constructive" in event.payload["report"].lower() for event in reports)
    assert any("risk" in event.payload["report"].lower() for event in reports)


def test_llm_runner_analyst_packets_disclose_when_live_source_data_is_absent():
    config = RunConfig(ticker="NVDA", trade_date="2026-05-06", execution_mode="real")

    reports = [
        event.payload["report"]
        for event in _analyst_events("run_123", config)
        if event.type == "report.updated"
    ]

    assert reports
    assert all("No live source payload is attached" in report for report in reports)


def test_research_prompt_requires_grounded_synthesis_only():
    prompt = _research_prompt(
        RunConfig(ticker="NVDA", trade_date="2026-05-06", execution_mode="real")
    )

    assert "Use only the analyst packets and run metadata supplied in this prompt" in prompt
    assert "Do not invent prices, earnings, URLs, filings, headlines, or source names" in prompt
    assert "If current source data is unavailable" in prompt


def test_llm_runner_injects_stored_market_data_snapshots_into_prompt(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    repo.upsert_provider_config(
        "lm-studio-llm",
        enabled=True,
        secret_ref=None,
        config={
            "auth_required": False,
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "local-qwen",
            "provider": "openai-compatible",
        },
    )
    repo.upsert_provider_role_assignment("research_llm", provider_id="lm-studio-llm")
    repo.store_market_data_snapshot(
        provider_id="alpaca-market-data",
        symbol="NVDA",
        snapshot_kind="quote",
        feed="iex",
        payload={
            "quote": {
                "symbol": "NVDA",
                "timestamp": "2026-05-06T15:31:00Z",
                "bid_price": 838.95,
                "bid_size": 200,
                "ask_price": 839.1,
                "ask_size": 300,
            }
        },
    )
    repo.store_market_data_snapshot(
        provider_id="alpaca-market-data",
        symbol="NVDA",
        snapshot_kind="bars",
        feed="iex",
        timeframe="1Min",
        payload={
            "bars": [
                {
                    "symbol": "NVDA",
                    "timestamp": "2026-05-06T15:30:00Z",
                    "open": 838.12,
                    "high": 841.0,
                    "low": 836.5,
                    "close": 839.05,
                    "volume": 6601542,
                    "vwap": 838.71,
                    "trade_count": 9342,
                }
            ]
        },
    )
    captured: dict[str, object] = {}

    class FakeLlm:
        def invoke(self, prompt: str):
            captured["prompt"] = prompt
            return (
                '{"rating":"Neutral","action":"Watch","thesis":"Stored market data reviewed.",'
                '"risk_notes":"Verify before trading.","confidence":0.62}'
            )

    class FakeLlmClient:
        def get_llm(self):
            return FakeLlm()

    runner = LlmResearchRunner(
        repo,
        secret_store_factory=lambda secret_ref: None,
        llm_client_factory=lambda *args, **kwargs: FakeLlmClient(),
    )

    runner(
        "run_123",
        RunConfig(ticker="NVDA", trade_date="2026-05-06", execution_mode="real"),
    )

    prompt = str(captured["prompt"])
    assert "Verified stored market-data snapshots" in prompt
    assert "Quote alpaca-market-data iex at 2026-05-06T15:31:00Z: bid 838.95 x 200, ask 839.1 x 300" in prompt
    assert "Bars alpaca-market-data iex 1Min: 1 bars" in prompt


def test_llm_runner_uses_configured_research_llm_role(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    repo.upsert_provider_config(
        "lm-studio-llm",
        enabled=True,
        secret_ref="env:LM_STUDIO_KEY",
        config={
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "local-qwen",
            "provider": "openai-compatible",
        },
    )
    repo.upsert_provider_role_assignment("research_llm", provider_id="lm-studio-llm")
    captured: dict[str, object] = {}

    class FakeSecretStore:
        def get_secret(self, secret_ref: str) -> str:
            captured["secret_ref"] = secret_ref
            return "local-key"

    class FakeLlm:
        def invoke(self, prompt: str):
            captured["prompt"] = prompt
            return (
                '{"rating":"Neutral","action":"Watch","thesis":"Local model reviewed NVDA.",'
                '"risk_notes":"Size carefully.","confidence":0.64}'
            )

    class FakeLlmClient:
        def get_llm(self):
            return FakeLlm()

    def fake_llm_client_factory(provider: str, model: str, **kwargs):
        captured["provider"] = provider
        captured["model"] = model
        captured.update(kwargs)
        return FakeLlmClient()

    runner = LlmResearchRunner(
        repo,
        secret_store_factory=lambda secret_ref: FakeSecretStore(),
        llm_client_factory=fake_llm_client_factory,
    )

    result = runner(
        "run_123",
        RunConfig(ticker="NVDA", trade_date="2026-05-06", execution_mode="real"),
    )
    source_event = next(event for event in result.events if event.type == "tool.called")

    assert captured["secret_ref"] == "env:LM_STUDIO_KEY"
    assert captured["provider"] == "openai-compatible"
    assert captured["model"] == "local-qwen"
    assert captured["base_url"] == "http://127.0.0.1:1234/v1"
    assert result.action == "Watch"
    assert source_event.payload["provider"] == "lm-studio-llm"
    assert source_event.payload["fallback"] is False


def test_llm_runner_allows_local_lm_studio_without_secret_ref(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    repo.upsert_provider_config(
        "lm-studio-llm",
        enabled=True,
        secret_ref=None,
        config={
            "auth_required": False,
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "local-qwen",
            "provider": "openai-compatible",
        },
    )
    repo.upsert_provider_role_assignment("research_llm", provider_id="lm-studio-llm")
    captured: dict[str, object] = {}

    class FakeLlm:
        def invoke(self, prompt: str):
            captured["prompt"] = prompt
            return (
                '{"rating":"Neutral","action":"Watch","thesis":"Local model reviewed NVDA.",'
                '"risk_notes":"Size carefully.","confidence":0.64}'
            )

    class FakeLlmClient:
        def get_llm(self):
            return FakeLlm()

    def fake_secret_store_factory(secret_ref: str):
        raise AssertionError("LM Studio without auth must not request a secret")

    def fake_llm_client_factory(provider: str, model: str, **kwargs):
        captured["provider"] = provider
        captured["model"] = model
        captured.update(kwargs)
        return FakeLlmClient()

    runner = LlmResearchRunner(
        repo,
        secret_store_factory=fake_secret_store_factory,
        llm_client_factory=fake_llm_client_factory,
    )

    result = runner(
        "run_123",
        RunConfig(ticker="NVDA", trade_date="2026-05-06", execution_mode="real"),
    )
    source_event = next(event for event in result.events if event.type == "tool.called")

    assert captured["provider"] == "openai-compatible"
    assert captured["api_key"] == "lm-studio"
    assert source_event.payload["provider"] == "lm-studio-llm"
    assert source_event.payload["fallback"] is False


def test_llm_runner_allows_codex_developer_mode_without_secret_ref(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    repo.upsert_provider_config(
        "openai-codex-oauth-llm",
        enabled=True,
        secret_ref=None,
        config={
            "auth_required": False,
            "developer_mode": True,
            "model": "gpt-5.4-mini",
            "provider": "codex-oauth",
            "runner_supported": True,
            "graph_runner_supported": True,
        },
    )
    repo.upsert_provider_role_assignment("research_llm", provider_id="openai-codex-oauth-llm")
    captured: dict[str, object] = {}

    class FakeLlm:
        def invoke(self, prompt: str):
            captured["prompt"] = prompt
            return (
                '{"rating":"Neutral","action":"Watch","thesis":"Codex reviewed NVDA quickly.",'
                '"risk_notes":"Developer mode only.","confidence":0.66}'
            )

    class FakeLlmClient:
        def get_llm(self):
            return FakeLlm()

    def fake_secret_store_factory(secret_ref: str):
        raise AssertionError("Codex developer mode must not request a secret")

    def fake_llm_client_factory(provider: str, model: str, **kwargs):
        captured["provider"] = provider
        captured["model"] = model
        captured.update(kwargs)
        return FakeLlmClient()

    runner = LlmResearchRunner(
        repo,
        secret_store_factory=fake_secret_store_factory,
        llm_client_factory=fake_llm_client_factory,
    )

    result = runner(
        "run_123",
        RunConfig(ticker="NVDA", trade_date="2026-05-06", execution_mode="real"),
    )
    source_event = next(event for event in result.events if event.type == "tool.called")

    assert captured["provider"] == "codex-oauth"
    assert captured["model"] == "gpt-5.4-mini"
    assert captured["api_key"] == "developer-mode"
    assert result.action == "Watch"
    assert source_event.payload["provider"] == "openai-codex-oauth-llm"
    assert source_event.payload["fallback"] is False


def test_llm_runner_replaces_non_english_risk_notes(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    repo.upsert_provider_config(
        "lm-studio-llm",
        enabled=True,
        secret_ref=None,
        config={
            "auth_required": False,
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "local-qwen",
            "provider": "openai-compatible",
        },
    )
    repo.upsert_provider_role_assignment("research_llm", provider_id="lm-studio-llm")

    class FakeLlm:
        def invoke(self, prompt: str):
            assert "English only" in prompt
            return (
                '{"rating":"Neutral","action":"Watch","thesis":"Local model reviewed NVDA.",'
                '"risk_notes":"高度估值敏感性；芯片供应链扰动风险；政策监管升级","confidence":0.64}'
            )

    class FakeLlmClient:
        def get_llm(self):
            return FakeLlm()

    runner = LlmResearchRunner(
        repo,
        secret_store_factory=lambda secret_ref: None,
        llm_client_factory=lambda *args, **kwargs: FakeLlmClient(),
    )

    result = runner(
        "run_123",
        RunConfig(ticker="NVDA", trade_date="2026-05-06", execution_mode="real"),
    )

    assert result.risk_notes == "Risk review required before any paper order."


def test_llm_runner_falls_back_when_local_model_endpoint_is_down(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    repo.upsert_provider_config(
        "lm-studio-llm",
        enabled=True,
        secret_ref=None,
        config={
            "auth_required": False,
            "base_url": "http://127.0.0.1:1234/v1",
            "model": "local-qwen",
            "provider": "openai-compatible",
        },
    )
    repo.upsert_provider_role_assignment("research_llm", provider_id="lm-studio-llm")

    class BrokenLlm:
        def invoke(self, prompt: str):
            raise Exception("LM Studio is not reachable")

    class BrokenLlmClient:
        def get_llm(self):
            return BrokenLlm()

    runner = LlmResearchRunner(
        repo,
        secret_store_factory=lambda secret_ref: None,
        llm_client_factory=lambda *args, **kwargs: BrokenLlmClient(),
    )

    result = runner(
        "run_123",
        RunConfig(ticker="NVDA", trade_date="2026-05-06", execution_mode="real"),
    )
    decision = next(event for event in result.events if event.type == "decision.created")

    assert decision.payload["fallback"] is True
    assert result.action == "Hold"
