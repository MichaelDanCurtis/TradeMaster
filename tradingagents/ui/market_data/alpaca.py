from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

import requests

from tradingagents.ui.market_data.base import BarTimeframe, MarketDataBar, MarketDataQuote
from tradingagents.ui.secrets import SecretStore


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, Any]: ...

    def raise_for_status(self) -> None: ...


class HttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, object],
        timeout: float,
    ) -> HttpResponse:
        ...


class AlpacaMarketDataProvider:
    def __init__(
        self,
        *,
        secret_store: SecretStore,
        secret_ref: str,
        http_client: HttpClient | None = None,
        base_url: str = "https://data.alpaca.markets",
        timeout: float = 15.0,
    ) -> None:
        self._secret_store = secret_store
        self._secret_ref = secret_ref
        self._http_client = http_client or requests
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def historical_bars(
        self,
        *,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: BarTimeframe,
        limit: int | None = None,
        feed: str | None = None,
    ) -> list[MarketDataBar]:
        normalized_symbol = _normalize_symbol(symbol)
        params: dict[str, object] = {
            "start": _isoformat_utc(start),
            "end": _isoformat_utc(end),
            "timeframe": timeframe,
        }
        if limit is not None:
            params["limit"] = limit
        if feed is not None:
            params["feed"] = feed

        response = self._http_client.get(
            f"{self._base_url}/v2/stocks/{normalized_symbol}/bars",
            headers=self._headers(),
            params=params,
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return [
            _bar_from_alpaca(normalized_symbol, bar)
            for bar in payload.get("bars", [])
        ]

    def latest_quote(self, symbol: str, *, feed: str | None = None) -> MarketDataQuote:
        normalized_symbol = _normalize_symbol(symbol)
        params: dict[str, object] = {}
        if feed is not None:
            params["feed"] = feed

        response = self._http_client.get(
            f"{self._base_url}/v2/stocks/{normalized_symbol}/quotes/latest",
            headers=self._headers(),
            params=params,
            timeout=self._timeout,
        )
        response.raise_for_status()
        return _quote_from_alpaca(normalized_symbol, response.json()["quote"])

    def stock_movers(self, *, top: int = 25) -> dict[str, Any]:
        """Top market movers from the Alpaca stock screener.

        Returns the raw payload: ``{"gainers": [{"symbol", "price", "change",
        "percent_change"}], "losers": [...], "last_updated", "market_type"}``.
        """
        response = self._http_client.get(
            f"{self._base_url}/v1beta1/screener/stocks/movers",
            headers=self._headers(),
            params={"top": top},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def most_active_stocks(self, *, by: str = "volume", top: int = 25) -> dict[str, Any]:
        """Most-active stocks from the Alpaca stock screener.

        Returns the raw payload: ``{"most_actives": [{"symbol", "volume",
        "trade_count"}], "last_updated"}``. Entries carry no price.
        """
        response = self._http_client.get(
            f"{self._base_url}/v1beta1/screener/stocks/most-actives",
            headers=self._headers(),
            params={"by": by, "top": top},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def _headers(self) -> dict[str, str]:
        credentials = _parse_credentials(self._secret_store.get_secret(self._secret_ref))
        return {
            "APCA-API-KEY-ID": credentials["key_id"],
            "APCA-API-SECRET-KEY": credentials["secret_key"],
        }


def _parse_credentials(raw_secret: str) -> dict[str, str]:
    payload = json.loads(raw_secret)
    key_id = payload.get("key_id") or payload.get("key")
    secret_key = payload.get("secret_key") or payload.get("secret")
    if not key_id or not secret_key:
        raise ValueError("Alpaca secret must include key_id and secret_key")
    return {"key_id": str(key_id), "secret_key": str(secret_key)}


def _bar_from_alpaca(symbol: str, bar: Mapping[str, Any]) -> MarketDataBar:
    return MarketDataBar(
        symbol=symbol,
        timestamp=_parse_alpaca_timestamp(str(bar["t"])),
        open=float(bar["o"]),
        high=float(bar["h"]),
        low=float(bar["l"]),
        close=float(bar["c"]),
        volume=int(bar["v"]),
        vwap=float(bar["vw"]) if bar.get("vw") is not None else None,
        trade_count=int(bar["n"]) if bar.get("n") is not None else None,
    )


def _quote_from_alpaca(symbol: str, quote: Mapping[str, Any]) -> MarketDataQuote:
    return MarketDataQuote(
        symbol=symbol,
        timestamp=_parse_alpaca_timestamp(str(quote["t"])),
        bid_price=float(quote["bp"]),
        bid_size=int(quote["bs"]),
        ask_price=float(quote["ap"]),
        ask_size=int(quote["as"]),
    )


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("symbol must not be empty")
    return normalized


def _isoformat_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_alpaca_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
