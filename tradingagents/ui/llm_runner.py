from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.ui.events import RunConfig, RunEvent
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import RealRunResult
from tradingagents.ui.secrets import SecretNotFoundError, SecretStore


OPENAI_LLM_PROVIDER_ID = "openai-llm"


@dataclass(frozen=True)
class LlmResearchDecision:
    rating: str
    action: str
    thesis: str
    risk_notes: str
    confidence: float
    raw_response: str


SecretStoreFactory = Callable[[str], SecretStore]


class LlmResearchRunner:
    """Small approval-safe LLM runner for the UI agent cockpit.

    This runner exercises the event ledger and report workflow with a real LLM
    when an enabled provider has a resolvable secret. It deliberately returns a
    decision and optional paper preview context only; broker submission remains
    outside the runner and stays approval-gated.
    """

    def __init__(
        self,
        repository: UiRepository,
        *,
        secret_store_factory: SecretStoreFactory,
        llm_client_factory: Callable[..., Any] = create_llm_client,
    ) -> None:
        self._repository = repository
        self._secret_store_factory = secret_store_factory
        self._llm_client_factory = llm_client_factory

    def __call__(self, run_id: str, config: RunConfig) -> RealRunResult:
        provider = self._repository.get_provider_config(OPENAI_LLM_PROVIDER_ID)
        analyst_events = _analyst_events(run_id, config)

        if not provider.enabled or provider.secret_ref is None:
            decision = _fallback_decision(
                config,
                reason="openai-llm provider is disabled or missing a secret_ref",
            )
            return RealRunResult(
                events=[
                    *analyst_events,
                    _event(
                        run_id,
                        1,
                        "tool.called",
                        "Research Manager",
                        "LLM provider unavailable; using deterministic synthesis fallback.",
                        {
                            "provider": OPENAI_LLM_PROVIDER_ID,
                            "fallback": True,
                            "reason": "provider_not_configured",
                        },
                    ),
                    _decision_event(run_id, decision, fallback=True),
                ],
                rating=decision.rating,
                action=decision.action,
                thesis=decision.thesis,
                risk_notes=decision.risk_notes,
            )

        try:
            api_key = self._secret_store_factory(provider.secret_ref).get_secret(provider.secret_ref)
            decision = self._invoke_llm(config, provider.config, api_key)
            fallback = False
        except (SecretNotFoundError, ValueError, RuntimeError) as exc:
            decision = _fallback_decision(config, reason=str(exc))
            fallback = True

        source_event = _event(
            run_id,
            1,
            "tool.called",
            "Research Manager",
            "Requested LLM synthesis from OpenAI provider."
            if not fallback
            else "LLM synthesis failed; using deterministic fallback.",
            {
                "provider": OPENAI_LLM_PROVIDER_ID,
                "fallback": fallback,
                "model": provider.config.get("model") or config.deep_model,
            },
        )
        return RealRunResult(
            events=[
                *analyst_events,
                source_event,
                _event(
                    run_id,
                    1,
                    "report.updated",
                    "Research Manager",
                    "Synthesized analyst reports into an investment stance.",
                    {
                        "confidence": decision.confidence,
                        "fallback": fallback,
                    },
                ),
                _decision_event(run_id, decision, fallback=fallback),
            ],
            rating=decision.rating,
            action=decision.action,
            thesis=decision.thesis,
            risk_notes=decision.risk_notes,
        )

    def _invoke_llm(
        self,
        config: RunConfig,
        provider_config: dict[str, object],
        api_key: str,
    ) -> LlmResearchDecision:
        model = str(provider_config.get("model") or config.deep_model)
        base_url = _optional_string(provider_config.get("base_url"))
        llm_client = self._llm_client_factory(
            "openai",
            model,
            base_url=base_url,
            api_key=api_key,
            timeout=float(provider_config.get("timeout", 60)),
        )
        llm = llm_client.get_llm()
        response = llm.invoke(_research_prompt(config))
        raw_response = _response_text(response)
        payload = _extract_json_payload(raw_response)

        return LlmResearchDecision(
            rating=str(payload.get("rating") or "Neutral").strip() or "Neutral",
            action=str(payload.get("action") or "Hold").strip() or "Hold",
            thesis=str(payload.get("thesis") or raw_response).strip(),
            risk_notes=str(payload.get("risk_notes") or "Risk review required before any paper order.").strip(),
            confidence=float(payload.get("confidence") or 0.5),
            raw_response=raw_response,
        )


def _analyst_events(run_id: str, config: RunConfig) -> list[RunEvent]:
    names = {
        "market": "Market Analyst",
        "news": "News Analyst",
        "social": "Social Analyst",
        "fundamentals": "Fundamentals Analyst",
    }
    events: list[RunEvent] = []
    for analyst in config.analysts:
        node = names[analyst]
        events.extend(
            [
                _event(run_id, 1, "agent.started", node, f"{node} started.", {"analyst": analyst}),
                _event(
                    run_id,
                    1,
                    "report.updated",
                    node,
                    f"{node} prepared context for LLM synthesis.",
                    {"section": analyst, "source": "local-market-context"},
                ),
            ]
        )
    return events


def _decision_event(run_id: str, decision: LlmResearchDecision, *, fallback: bool) -> RunEvent:
    return _event(
        run_id,
        1,
        "decision.created",
        "Portfolio Manager",
        f"Created {'fallback ' if fallback else ''}LLM research decision.",
        {
            "rating": decision.rating,
            "action": decision.action,
            "confidence": decision.confidence,
            "fallback": fallback,
            "thesis": decision.thesis,
            "risk_notes": decision.risk_notes,
        },
    )


def _fallback_decision(config: RunConfig, *, reason: str) -> LlmResearchDecision:
    return LlmResearchDecision(
        rating="Neutral",
        action="Hold",
        thesis=(
            f"{config.ticker} research run completed without a live LLM. "
            "The deterministic fallback keeps the cockpit, DAG, event ledger, and paper-preview path testable."
        ),
        risk_notes=f"LLM fallback reason: {reason}. Human review required before any trade preview is acted on.",
        confidence=0.35,
        raw_response="",
    )


def _research_prompt(config: RunConfig) -> str:
    analysts = ", ".join(config.analysts)
    return (
        "You are the Wealth Agents research manager. Create a concise investment research synthesis. "
        "Do not claim certainty and do not place trades. "
        "Return only JSON with keys rating, action, thesis, risk_notes, confidence. "
        f"Ticker: {config.ticker}. Trade date: {config.trade_date}. "
        f"Analyst packets available: {analysts}. Research depth: {config.research_depth}. "
        "Allowed actions are Buy, Hold, Sell, Watch, or Avoid. "
        "The output is advisory and any broker action requires human approval."
    )


def _extract_json_payload(raw_response: str) -> dict[str, object]:
    text = raw_response.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("LLM response JSON must be an object")
    return payload


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    return str(content)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _event(
    run_id: str,
    sequence: int,
    event_type: str,
    node: str | None,
    message: str,
    payload: dict[str, object],
) -> RunEvent:
    return RunEvent(
        run_id=run_id,
        sequence=sequence,
        type=event_type,
        node=node,
        message=message,
        payload=payload,
    )
