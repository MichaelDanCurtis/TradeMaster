"""
Finnhub data adapter.

Ported from AlpacaTradingAgent's dataflows. Uses httpx for consistency with
the rest of TM's HTTP code. Reads FINNHUB_API_KEY from the environment.

Only `fetch_company_news` is exposed today; insider sentiment / transactions
and earnings will follow when the corresponding UI surfaces want them.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

_FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
_FINNHUB_TIMEOUT_SECONDS = 15.0


class FinnhubError(RuntimeError):
    """Raised when the Finnhub API key is missing or the API returns an error."""


def _api_key() -> str:
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        raise FinnhubError("FINNHUB_API_KEY is not set")
    return key


def fetch_company_news(
    symbol: str,
    *,
    start_date: str,
    end_date: str,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch company news for `symbol` within [start_date, end_date].

    Dates are YYYY-MM-DD. Returns Finnhub's raw items sorted by datetime
    descending (most recent first). Caller normalizes via `normalize_news_item`.
    """

    params = {
        "symbol": symbol.upper(),
        "from": start_date,
        "to": end_date,
        "token": _api_key(),
    }

    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=_FINNHUB_TIMEOUT_SECONDS)

    try:
        response = client.get(f"{_FINNHUB_BASE_URL}/company-news", params=params)
        response.raise_for_status()
        data = response.json()
    finally:
        if own_client and client is not None:
            client.close()

    if not isinstance(data, list):
        return []

    items = [entry for entry in data if isinstance(entry, dict)]
    items.sort(key=lambda entry: entry.get("datetime", 0) or 0, reverse=True)
    return items


def fetch_general_news(
    *,
    category: str = "general",
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch general market headlines (Finnhub's free ``/news`` endpoint).

    Mirrors :func:`fetch_company_news`: returns raw Finnhub items sorted by
    datetime descending. Items carry a ``related`` CSV of tickers that the
    discovery funnel mines for candidate symbols.
    """

    params = {
        "category": category,
        "token": _api_key(),
    }

    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=_FINNHUB_TIMEOUT_SECONDS)

    try:
        response = client.get(f"{_FINNHUB_BASE_URL}/news", params=params)
        response.raise_for_status()
        data = response.json()
    finally:
        if own_client and client is not None:
            client.close()

    if not isinstance(data, list):
        return []

    items = [entry for entry in data if isinstance(entry, dict)]
    items.sort(key=lambda entry: entry.get("datetime", 0) or 0, reverse=True)
    return items


def normalize_news_item(item: dict[str, Any]) -> dict[str, Any]:
    """
    Reshape a raw Finnhub news item into a stable, client-friendly form.

    Returned shape (every key always present, may be `null`/empty string):
      id, published_at (ISO 8601 UTC), source, headline, summary, url,
      category, related (CSV of tickers), image (URL or None).
    """

    ts = item.get("datetime")
    if isinstance(ts, (int, float)) and ts > 0:
        published_at: str | None = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    else:
        published_at = None

    image = item.get("image")
    if isinstance(image, str):
        image_value: str | None = image or None
    else:
        image_value = None

    return {
        "id": str(item.get("id") or ""),
        "published_at": published_at,
        "source": str(item.get("source") or ""),
        "headline": str(item.get("headline") or ""),
        "summary": str(item.get("summary") or ""),
        "url": str(item.get("url") or ""),
        "category": str(item.get("category") or "company"),
        "related": str(item.get("related") or ""),
        "image": image_value,
    }
