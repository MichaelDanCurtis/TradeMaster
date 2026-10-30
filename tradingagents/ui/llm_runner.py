from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.ui.events import RunConfig, RunEvent
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import RealRunResult
from tradingagents.ui.secrets import SecretNotFoundError, SecretStore


DEFAULT_RESEARCH_LLM_PROVIDER_ID = "openai-llm"
RESEARCH_LLM_ROLE_KEY = "research_llm"
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_NON_ENGLISH_THESIS_NOTICE = (
    "LLM returned a non-English thesis. Re-run the report with the English-only research setting."
)
ANALYST_PROGRESS_NODE_NAMES = {
    "market": "Market Analyst",
    "news": "News Analyst",
    "social": "Social Analyst",
    "fundamentals": "Fundamentals Analyst",
}


@dataclass(frozen=True)
class LlmResearchDecision:
    rating: str
    action: str
    thesis: str
    risk_notes: str
    confidence: float
    raw_response: str


@dataclass(frozen=True)
class MarketEvidence:
    lines: tuple[str, ...] = ()

    @property
    def has_live_payload(self) -> bool:
        return bool(self.lines)

    def text_block(self) -> str:
        if not self.lines:
            return "No verified market-data snapshot is attached for this ticker."
        return "Verified stored market-data snapshots:\n" + "\n".join(f"- {line}" for line in self.lines)


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
        provider_id = self._research_llm_provider_id()
        provider = self._repository.get_provider_config(provider_id)
        market_evidence = _market_evidence(self._repository, config)
        analyst_events = _analyst_events(run_id, config, market_evidence)
        debate_events = _debate_events(run_id, config)

        if not provider.enabled or _provider_requires_secret(provider.config) and provider.secret_ref is None:
            decision = _fallback_decision(
                config,
                reason=f"{provider_id} provider is disabled or missing a required secret_ref",
            )
            return RealRunResult(
                events=[
                    *analyst_events,
                    *debate_events,
                    _event(
                        run_id,
                        1,
                        "tool.called",
                        "Research Manager",
                        "LLM provider unavailable; using deterministic synthesis fallback.",
                        {
                            "provider": provider_id,
                            "fallback": True,
                            "reason": "provider_not_configured",
                        },
                    ),
                    *_decision_path_events(run_id, decision, fallback=True),
                    _decision_event(run_id, decision, fallback=True),
                ],
                rating=decision.rating,
                action=decision.action,
                thesis=decision.thesis,
                risk_notes=decision.risk_notes,
            )

        try:
            api_key = _provider_api_key(provider.config)
            if provider.secret_ref is not None:
                api_key = self._secret_store_factory(provider.secret_ref).get_secret(provider.secret_ref)
            decision = self._invoke_llm(config, provider.config, api_key, market_evidence)
            fallback = False
        except Exception as exc:
            decision = _fallback_decision(config, reason=str(exc))
            fallback = True

        source_event = _event(
            run_id,
            1,
            "tool.called",
            "Research Manager",
            f"Requested LLM synthesis from {provider.name} provider."
            if not fallback
            else "LLM synthesis failed; using deterministic fallback.",
            {
                "provider": provider_id,
                "fallback": fallback,
                "model": provider.config.get("model") or config.deep_model,
            },
        )
        return RealRunResult(
            events=[
                *analyst_events,
                *debate_events,
                source_event,
                *_decision_path_events(run_id, decision, fallback=fallback),
                _decision_event(run_id, decision, fallback=fallback),
            ],
            rating=decision.rating,
            action=decision.action,
            thesis=decision.thesis,
            risk_notes=decision.risk_notes,
        )

    def _research_llm_provider_id(self) -> str:
        assignments = self._repository.list_provider_role_assignments()
        assignment = next(
            (
                item
                for item in assignments
                if item.role_key == RESEARCH_LLM_ROLE_KEY
            ),
            None,
        )
        return assignment.provider_id if assignment is not None else DEFAULT_RESEARCH_LLM_PROVIDER_ID

    def _invoke_llm(
        self,
        config: RunConfig,
        provider_config: dict[str, object],
        api_key: str,
        market_evidence: MarketEvidence | None = None,
    ) -> LlmResearchDecision:
        model = str(provider_config.get("model") or config.deep_model)
        provider = str(provider_config.get("provider") or "openai")
        base_url = _optional_string(provider_config.get("base_url"))
        llm_client = self._llm_client_factory(
            provider,
            model,
            base_url=base_url,
            api_key=api_key,
            timeout=float(provider_config.get("timeout", 60)),
        )
        llm = llm_client.get_llm()
        response = llm.invoke(_research_prompt(config, market_evidence))
        raw_response = _response_text(response)
        payload = _extract_json_payload(raw_response)

        return LlmResearchDecision(
            rating=str(payload.get("rating") or "Neutral").strip() or "Neutral",
            action=str(payload.get("action") or "Hold").strip() or "Hold",
            thesis=_english_or_default(payload.get("thesis"), _NON_ENGLISH_THESIS_NOTICE),
            risk_notes=_english_or_default(payload.get("risk_notes"), "Risk review required before any paper order."),
            confidence=_confidence_value(payload.get("confidence")),
            raw_response=raw_response,
        )


def _analyst_events(
    run_id: str,
    config: RunConfig,
    market_evidence: MarketEvidence | None = None,
) -> list[RunEvent]:
    events: list[RunEvent] = []
    for analyst in config.analysts:
        node = ANALYST_PROGRESS_NODE_NAMES[analyst]
        report = _analyst_report_text(config, analyst, node, market_evidence)
        events.extend(
            [
                _event(run_id, 1, "agent.started", node, f"{node} started.", {"analyst": analyst}),
                _event(
                    run_id,
                    1,
                    "report.updated",
                    node,
                    f"{node} prepared context for LLM synthesis.",
                    {"report": report, "section": analyst, "source": "local-market-context"},
                ),
            ]
        )
    return events


def _debate_events(run_id: str, config: RunConfig) -> list[RunEvent]:
    return [
        _event(
            run_id,
            1,
            "agent.started",
            "Bull Researcher",
            "Bull Researcher started.",
            {"agent": "bull_researcher", "ticker": config.ticker},
        ),
        _event(
            run_id,
            1,
            "report.updated",
            "Bull Researcher",
            "Prepared constructive case from analyst packets.",
            {
                "report": (
                    f"Constructive thesis for {config.ticker}: analyst packets support a watchful bullish case "
                    "when market structure, news tone, social confirmation, and fundamentals are aligned. "
                    "Position sizing still requires the manager and risk review."
                ),
                "section": "bull_thesis",
            },
        ),
        _event(
            run_id,
            1,
            "agent.started",
            "Bear Researcher",
            "Bear Researcher started.",
            {"agent": "bear_researcher", "ticker": config.ticker},
        ),
        _event(
            run_id,
            1,
            "report.updated",
            "Bear Researcher",
            "Prepared downside case and challenge points.",
            {
                "report": (
                    f"Downside thesis for {config.ticker}: challenge the setup for valuation pressure, headline "
                    "risk, crowded positioning, and weak confirmation. This report exists to keep the final "
                    "stance from becoming a one-sided momentum call."
                ),
                "section": "bear_thesis",
            },
        ),
    ]


def _decision_path_events(
    run_id: str,
    decision: LlmResearchDecision,
    *,
    fallback: bool,
) -> list[RunEvent]:
    return [
        _event(
            run_id,
            1,
            "report.updated",
            "Research Manager",
            "Synthesized analyst reports and bull/bear debate into an investment stance.",
            {
                "confidence": decision.confidence,
                "fallback": fallback,
                "report": decision.thesis,
                "rating": decision.rating,
                "action": decision.action,
            },
        ),
        _event(
            run_id,
            1,
            "agent.started",
            "Trader",
            "Trader started transaction proposal review.",
            {"agent": "trader", "proposal_mode": "advisory"},
        ),
        _event(
            run_id,
            1,
            "report.updated",
            "Trader",
            "Translated research stance into an approval-gated trade proposal.",
            {
                "action": decision.action,
                "report": (
                    f"Trade proposal: {decision.action} remains advisory only. The trader converts the research "
                    "stance into a paper-preview candidate and leaves broker submission behind human approval."
                ),
                "section": "trade_proposal",
            },
        ),
        _event(
            run_id,
            1,
            "agent.started",
            "Risk Manager",
            "Risk Manager started execution constraint review.",
            {"agent": "risk_manager", "authority": "advisory"},
        ),
        _event(
            run_id,
            1,
            "report.updated",
            "Risk Manager",
            "Attached risk notes and kept broker authority approval-gated.",
            {
                "report": decision.risk_notes,
                "risk_notes": decision.risk_notes,
                "section": "risk_review",
            },
        ),
    ]


def _analyst_report_text(
    config: RunConfig,
    analyst: str,
    node: str,
    market_evidence: MarketEvidence | None = None,
) -> str:
    focus = {
        "market": "price action, volume, VWAP, moving averages, and technical confirmation",
        "news": "company headlines, macro events, and policy-sensitive catalysts",
        "social": "public sentiment, narrative velocity, and crowding risk",
        "fundamentals": "financial quality, growth durability, valuation, and balance-sheet risk",
    }.get(analyst, "available evidence")
    evidence = market_evidence or MarketEvidence()
    live_payload_note = (
        f"Attached evidence:\n{evidence.text_block()}"
        if analyst == "market" and evidence.has_live_payload
        else "No live source payload is attached to this packet yet."
    )
    return (
        f"{node} packet for {config.ticker}: requested review focus is {focus} for the "
        f"{config.trade_date} research run. {live_payload_note} "
        "Treat missing source payloads as research coverage requests, not evidence that current market facts were retrieved."
    )


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


def _market_evidence(repository: UiRepository, config: RunConfig) -> MarketEvidence:
    snapshots = repository.list_market_data_snapshots(symbol=config.ticker)
    quote = next((snapshot for snapshot in snapshots if snapshot.snapshot_kind == "quote"), None)
    bars = next((snapshot for snapshot in snapshots if snapshot.snapshot_kind == "bars"), None)

    lines: list[str] = []
    if quote is not None:
        quote_payload = _payload_mapping(quote.payload.get("quote"))
        if quote_payload:
            lines.append(
                "Quote "
                f"{quote.provider_id} {_optional_display(quote.feed)} at {_optional_display(quote_payload.get('timestamp'))}: "
                f"bid {_optional_display(quote_payload.get('bid_price'))} x {_optional_display(quote_payload.get('bid_size'))}, "
                f"ask {_optional_display(quote_payload.get('ask_price'))} x {_optional_display(quote_payload.get('ask_size'))}"
            )

    if bars is not None:
        bar_payloads = [
            item for item in bars.payload.get("bars", []) if isinstance(item, dict)
        ]
        if bar_payloads:
            first_bar = bar_payloads[0]
            last_bar = bar_payloads[-1]
            highs = _numeric_values(bar_payloads, "high")
            lows = _numeric_values(bar_payloads, "low")
            total_volume = sum(_numeric_values(bar_payloads, "volume"))
            lines.append(
                "Bars "
                f"{bars.provider_id} {_optional_display(bars.feed)} {_optional_display(bars.timeframe)}: "
                f"{len(bar_payloads)} bars from {_optional_display(first_bar.get('timestamp'))} "
                f"to {_optional_display(last_bar.get('timestamp'))}; "
                f"last close {_optional_display(last_bar.get('close'))}; "
                f"range {_optional_display(min(lows) if lows else None)}-{_optional_display(max(highs) if highs else None)}; "
                f"volume {int(total_volume) if total_volume else 0}"
            )

    return MarketEvidence(tuple(lines))


def _payload_mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _numeric_values(items: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for item in items:
        try:
            values.append(float(item[key]))
        except (KeyError, TypeError, ValueError):
            continue
    return values


def _optional_display(value: object) -> str:
    if value is None or value == "":
        return "unknown"
    return str(value)


def _research_prompt(config: RunConfig, market_evidence: MarketEvidence | None = None) -> str:
    analysts = ", ".join(config.analysts)
    evidence = market_evidence or MarketEvidence()
    analyst_packets = "\n".join(
        f"- {_analyst_report_text(config, analyst, ANALYST_PROGRESS_NODE_NAMES[analyst], evidence)}"
        for analyst in config.analysts
    )
    return (
        "You are the Wealth Agents research manager. Create a concise investment research synthesis. "
        "Do not claim certainty and do not place trades. "
        "Use only the analyst packets and run metadata supplied in this prompt. "
        "Do not invent prices, earnings, URLs, filings, headlines, or source names. "
        "If current source data is unavailable, say that clearly in thesis and risk_notes. "
        "English only: every value in the JSON object must be written in English. "
        "Do not use Chinese or any non-English language. "
        "Return only a flat JSON object with keys rating, action, thesis, risk_notes, confidence. "
        "Do not add markdown, comments, nested objects, arrays, or any text outside the JSON object. "
        "Confidence must be a number from 0 to 1. "
        f"Ticker: {config.ticker}. Trade date: {config.trade_date}. "
        f"Analyst packets available: {analysts}. Research depth: {config.research_depth}. "
        f"Market evidence:\n{evidence.text_block()}\n"
        f"Analyst packet text:\n{analyst_packets}\n"
        "Allowed actions are Buy, Hold, Sell, Watch, or Avoid. "
        "The output is advisory and any broker action requires human approval."
    )


def _extract_json_payload(raw_response: str) -> dict[str, object]:
    text = raw_response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        payload = _extract_loose_payload(text)
        if payload is None:
            raise ValueError("LLM response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("LLM response JSON must be an object")
    return payload


def _extract_loose_payload(text: str) -> dict[str, object] | None:
    payload = {
        "rating": _extract_string_field(text, "rating"),
        "action": _extract_string_field(text, "action"),
        "thesis": _extract_string_field(text, "thesis"),
        "risk_notes": _extract_string_field(text, "risk_notes"),
        "confidence": _extract_scalar_field(text, "confidence"),
    }
    if not payload["rating"] or not payload["action"]:
        return None
    return {key: value for key, value in payload.items() if value is not None}


def _extract_string_field(text: str, field: str) -> str | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"(?P<value>.*?)"\s*(?:,|\n|}})', text, re.DOTALL)
    if not match:
        return None
    return match.group("value").replace('\\"', '"').strip().rstrip('"').strip()


def _extract_scalar_field(text: str, field: str) -> object | None:
    quoted = _extract_string_field(text, field)
    if quoted is not None:
        return quoted
    match = re.search(rf'"{re.escape(field)}"\s*:\s*(?P<value>-?\d+(?:\.\d+)?)', text)
    if not match:
        return None
    return float(match.group("value"))


def _confidence_value(value: object) -> float:
    if isinstance(value, int | float):
        return max(0.0, min(float(value), 1.0))
    text = str(value or "").strip().lower()
    if not text:
        return 0.5
    try:
        return max(0.0, min(float(text), 1.0))
    except ValueError:
        pass
    if "high" in text:
        return 0.75
    if "moderate" in text or "medium" in text:
        return 0.55
    if "low" in text:
        return 0.3
    return 0.5


def _english_or_default(value: object, default: str) -> str:
    text = str(value or "").strip()
    return default if not text or _CJK_RE.search(text) else text


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


def _provider_requires_secret(provider_config: dict[str, object]) -> bool:
    return provider_config.get("auth_required") is not False


def _provider_api_key(provider_config: dict[str, object]) -> str:
    configured = _optional_string(provider_config.get("api_key"))
    if configured is not None:
        return configured
    if provider_config.get("developer_mode") is True:
        return "developer-mode"
    return "lm-studio" if not _provider_requires_secret(provider_config) else ""


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
