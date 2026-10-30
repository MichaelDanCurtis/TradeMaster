"""Watcher condition evaluation and observation fetching."""

from __future__ import annotations

from dataclasses import dataclass
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from tradingagents.ui.market_data.base import MarketDataProvider


CONDITION_TYPES: tuple[str, ...] = (
    "price_above",
    "price_below",
    "change_pct_above",
    "change_pct_below",
    "volume_above",
)


@dataclass
class ConditionEvaluation:
    condition_type: str
    threshold: float
    observed_value: float
    fired: bool
    payload: dict[str, Any]


def evaluate_condition(
    *,
    condition_type: str,
    threshold: float,
    observed_value: float,
    payload: dict[str, Any] | None = None,
) -> ConditionEvaluation:
    """Pure boolean evaluation of a watcher condition."""
    if condition_type not in CONDITION_TYPES:
        raise ValueError(f"unsupported watcher condition: {condition_type}")
    if condition_type in {"price_above", "change_pct_above", "volume_above"}:
        fired = observed_value > threshold
    else:
        # price_below, change_pct_below
        fired = observed_value < threshold
    return ConditionEvaluation(
        condition_type=condition_type,
        threshold=threshold,
        observed_value=observed_value,
        fired=fired,
        payload=dict(payload or {}),
    )


def fetch_observation(
    provider: MarketDataProvider,
    *,
    symbol: str,
    condition_type: str,
    feed: str | None = None,
) -> tuple[float, dict[str, Any]]:
    """Fetch the observed value used to evaluate a condition for the symbol.

    Returns ``(observed_value, payload_extras)`` so the caller can persist the
    quote/bar context that drove the decision.
    """
    if condition_type in {"price_above", "price_below"}:
        quote = provider.latest_quote(symbol, feed=feed)
        if not all(math.isfinite(value) and value > 0 for value in (quote.bid_price, quote.ask_price)) or quote.ask_price < quote.bid_price:
            raise ValueError("Watcher needs a valid two-sided quote; no alert recorded")
        observed_at = quote.timestamp.replace(tzinfo=timezone.utc) if quote.timestamp.tzinfo is None else quote.timestamp
        age = (datetime.now(timezone.utc) - observed_at).total_seconds()
        if age < -60 or age > 300:
            raise ValueError("Watcher quote is stale or future-dated; no alert recorded")
        mid = (quote.bid_price + quote.ask_price) / 2.0
        return mid, {
            "source": "latest_quote",
            "bid": quote.bid_price,
            "ask": quote.ask_price,
            "timestamp": quote.timestamp.isoformat(),
        }

    if condition_type == "volume_above":
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=2)
        bars = provider.historical_bars(
            symbol=symbol,
            start=start,
            end=end,
            timeframe="1Day",
            limit=1,
            feed=feed,
        )
        if not bars:
            raise RuntimeError(f"no daily bar available for {symbol}")
        bar = bars[-1]
        return float(bar.volume), {
            "source": "daily_bar",
            "close": bar.close,
            "volume": bar.volume,
            "timestamp": bar.timestamp.isoformat(),
        }

    # change_pct_above / change_pct_below: compare last close to prior close.
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    bars = provider.historical_bars(
        symbol=symbol,
        start=start,
        end=end,
        timeframe="1Day",
        limit=10,
        feed=feed,
    )
    if len(bars) < 2:
        raise RuntimeError(f"need at least two daily bars for {symbol}")
    prior = bars[-2].close
    latest = bars[-1].close
    if prior == 0:
        raise RuntimeError(f"prior close is zero for {symbol}; cannot compute change")
    change_pct = ((latest - prior) / prior) * 100.0
    return change_pct, {
        "source": "daily_bar_pct_change",
        "prior_close": prior,
        "latest_close": latest,
        "timestamp": bars[-1].timestamp.isoformat(),
    }
