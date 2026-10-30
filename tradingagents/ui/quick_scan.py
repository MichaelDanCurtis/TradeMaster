"""Quick Scan — the cheap wide pass of the opportunity funnel.

One gpt-4o-mini call per symbol (Copilot Business seat, shared bearer cache)
with deterministic best-effort context: latest Alpaca quote + daily change and
up to three Finnhub headlines from the last 48 hours. Missing data degrades
the prompt; it never fails the scan. Only an unusable LLM response (after one
"JSON only" retry) or a per-symbol timeout marks a symbol failed.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from tradingagents.dataflows.finnhub_utils import fetch_company_news
from tradingagents.ui.market_data.base import MarketDataProvider

_LOG = logging.getLogger(__name__)

QUICK_SCAN_PROVIDER = "github-copilot-oauth"
QUICK_SCAN_MODEL = "gpt-4o-mini"
MAX_WORKERS = 6
PER_SYMBOL_BUDGET_SECONDS = 35.0
_MAX_COMPLETION_TOKENS = 300
_HEADLINE_LOOKBACK_HOURS = 48
_MAX_HEADLINES = 3

QUICK_SCAN_SYSTEM_PROMPT = (
    "You are a fast market screener for a personal trading desk. Given a stock "
    "symbol, its latest price context, and recent headlines, return a screening "
    "verdict as STRICT JSON only — no prose, no markdown, no code fences. "
    'Schema: {"stance": "buy"|"hold"|"avoid", "conviction": <int 0-100>, '
    '"thesis": "<=180 chars", "catalyst": "<=120 chars", "risk": "<=120 chars"}. '
    "Be decisive and concrete; conviction reflects how actionable the setup is "
    "right now."
)

_JSON_ONLY_REMINDER = (
    "Your previous reply was not parseable. Respond with ONLY the JSON object "
    "matching the schema. No prose, no code fences."
)


@dataclass(frozen=True)
class QuickScanOutcome:
    symbol: str
    stance: str
    conviction: int
    thesis: str
    catalyst: str
    risk: str
    model: str


@dataclass(frozen=True)
class QuickScanFailure:
    symbol: str
    error: str


def gather_symbol_context(
    symbol: str,
    provider: MarketDataProvider | None,
    *,
    feed: str | None = None,
) -> dict[str, Any]:
    """Best-effort deterministic context for the prompt. Never raises."""

    context: dict[str, Any] = {
        "price": None,
        "change_pct": None,
        "volume": None,
        "headlines": [],
    }
    if provider is not None:
        try:
            quote = provider.latest_quote(symbol, feed=feed)
            mid = (quote.bid_price + quote.ask_price) / 2.0
            if mid > 0:
                context["price"] = round(mid, 4)
        except Exception:  # noqa: BLE001 — missing quote degrades the prompt
            _LOG.debug("quickscan: no quote for %s", symbol, exc_info=True)
        try:
            end = datetime.now(timezone.utc)
            bars = provider.historical_bars(
                symbol=symbol,
                start=end - timedelta(days=7),
                end=end,
                timeframe="1Day",
                limit=2,
                feed=feed,
            )
            if bars:
                last = bars[-1]
                context["volume"] = int(last.volume)
                if context["price"] is None and last.close > 0:
                    context["price"] = round(float(last.close), 4)
                if len(bars) >= 2 and bars[-2].close > 0:
                    context["change_pct"] = round(
                        (last.close - bars[-2].close) / bars[-2].close * 100.0, 2
                    )
        except Exception:  # noqa: BLE001
            _LOG.debug("quickscan: no daily bars for %s", symbol, exc_info=True)

    try:
        now = datetime.now(timezone.utc)
        items = fetch_company_news(
            symbol,
            start_date=(now - timedelta(hours=_HEADLINE_LOOKBACK_HOURS + 24)).date().isoformat(),
            end_date=now.date().isoformat(),
        )
        cutoff = (now - timedelta(hours=_HEADLINE_LOOKBACK_HOURS)).timestamp()
        headlines: list[str] = []
        for item in items:
            ts = item.get("datetime")
            if isinstance(ts, (int, float)) and ts < cutoff:
                continue
            headline = str(item.get("headline") or "").strip()
            if headline:
                headlines.append(headline)
            if len(headlines) >= _MAX_HEADLINES:
                break
        context["headlines"] = headlines
    except Exception:  # noqa: BLE001 — missing FINNHUB_API_KEY or API error: skip silently
        _LOG.debug("quickscan: no headlines for %s", symbol, exc_info=True)

    return context


def build_user_prompt(symbol: str, context: dict[str, Any]) -> str:
    price = context.get("price")
    change_pct = context.get("change_pct")
    volume = context.get("volume")
    headlines = context.get("headlines") or []
    lines = [f"SYMBOL: {symbol}"]
    lines.append(f"Last price: {price if price is not None else 'unavailable'}")
    lines.append(
        f"Daily change: {f'{change_pct:+.2f}%' if change_pct is not None else 'unavailable'}"
    )
    lines.append(f"Daily volume: {volume if volume is not None else 'unavailable'}")
    if headlines:
        lines.append("Recent headlines (last 48h):")
        lines.extend(f"- {headline}" for headline in headlines)
    else:
        lines.append("Recent headlines (last 48h): none available")
    lines.append("Return the strict JSON verdict now.")
    return "\n".join(lines)


_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)


def parse_quick_scan_json(raw: str) -> dict[str, Any]:
    """Parse the screener's STRICT-JSON reply defensively. Raises ValueError."""

    text = _CODE_FENCE_RE.sub("", str(raw or "").strip()).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object in response")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON payload is not an object")

    stance = str(payload.get("stance") or "").strip().lower()
    if stance not in {"buy", "hold", "avoid"}:
        raise ValueError(f"unsupported stance: {stance!r}")

    raw_conviction = payload.get("conviction")
    try:
        conviction = int(float(raw_conviction))  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unparseable conviction: {raw_conviction!r}") from exc

    return {
        "stance": stance,
        "conviction": max(0, min(100, conviction)),
        "thesis": str(payload.get("thesis") or "").strip()[:180],
        "catalyst": str(payload.get("catalyst") or "").strip()[:120],
        "risk": str(payload.get("risk") or "").strip()[:120],
    }


def _default_llm_invoke(messages: list[tuple[str, str]]) -> str:
    from tradingagents.llm_clients.factory import create_llm_client

    client = create_llm_client(
        provider=QUICK_SCAN_PROVIDER,
        model=QUICK_SCAN_MODEL,
        temperature=0.1,
        timeout=30.0,
    )
    llm = client.get_llm()
    response = llm.invoke(messages, max_tokens=_MAX_COMPLETION_TOKENS)
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content)


def scan_one_symbol(
    symbol: str,
    provider: MarketDataProvider | None,
    *,
    feed: str | None = None,
    llm_invoke: Callable[[list[tuple[str, str]]], str] | None = None,
) -> QuickScanOutcome:
    """Context + one screener call (plus one JSON-only retry). Raises on failure."""

    invoke = llm_invoke or _default_llm_invoke
    context = gather_symbol_context(symbol, provider, feed=feed)
    messages: list[tuple[str, str]] = [
        ("system", QUICK_SCAN_SYSTEM_PROMPT),
        ("human", build_user_prompt(symbol, context)),
    ]
    raw = invoke(messages)
    try:
        parsed = parse_quick_scan_json(raw)
    except ValueError:
        retry_messages = [*messages, ("ai", str(raw)), ("human", _JSON_ONLY_REMINDER)]
        parsed = parse_quick_scan_json(invoke(retry_messages))
    return QuickScanOutcome(symbol=symbol, model=QUICK_SCAN_MODEL, **parsed)


def run_quick_scan(
    symbols: list[str],
    provider: MarketDataProvider | None,
    *,
    feed: str | None = None,
    llm_invoke: Callable[[list[tuple[str, str]]], str] | None = None,
    per_symbol_budget_seconds: float = PER_SYMBOL_BUDGET_SECONDS,
) -> tuple[list[QuickScanOutcome], list[QuickScanFailure]]:
    """Scan symbols in parallel (max 6 workers). Never raises per-symbol errors.

    A symbol that exceeds its wall-clock budget lands in failures; its worker
    thread is abandoned (``shutdown(wait=False)``) so the request never hangs.
    """

    if not symbols:
        return [], []
    waves = math.ceil(len(symbols) / MAX_WORKERS)
    deadline = time.monotonic() + per_symbol_budget_seconds * waves
    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="quickscan")
    outcomes: list[QuickScanOutcome] = []
    failures: list[QuickScanFailure] = []
    try:
        futures = {
            symbol: executor.submit(
                scan_one_symbol, symbol, provider, feed=feed, llm_invoke=llm_invoke
            )
            for symbol in symbols
        }
        for symbol, future in futures.items():
            remaining = max(0.0, deadline - time.monotonic())
            try:
                outcomes.append(future.result(timeout=remaining))
            except FutureTimeoutError:
                future.cancel()
                failures.append(
                    QuickScanFailure(
                        symbol=symbol,
                        error=f"timed out after {per_symbol_budget_seconds:.0f}s budget",
                    )
                )
            except Exception as exc:  # noqa: BLE001 — one bad symbol must not sink the batch
                failures.append(QuickScanFailure(symbol=symbol, error=str(exc)))
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return outcomes, failures
