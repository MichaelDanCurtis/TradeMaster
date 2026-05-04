from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

import requests

from tradingagents.ui.brokers.base import BrokerOrder, OrderSide
from tradingagents.ui.secrets import SecretStore


class HttpResponse(Protocol):
    def json(self) -> dict[str, Any]: ...

    def raise_for_status(self) -> None: ...


class HttpClient(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
    ) -> HttpResponse:
        ...


class AlpacaPaperBroker:
    broker_name = "alpaca"
    environment = "paper"

    def __init__(
        self,
        *,
        secret_store: SecretStore,
        secret_ref: str,
        price_estimator: Callable[[str], float],
        http_client: HttpClient | None = None,
        base_url: str = "https://paper-api.alpaca.markets",
        timeout: float = 15.0,
    ) -> None:
        self._secret_store = secret_store
        self._secret_ref = secret_ref
        self._price_estimator = price_estimator
        self._http_client = http_client or requests
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def estimate_price(self, symbol: str) -> float:
        return float(self._price_estimator(_normalize_symbol(symbol)))

    def submit_order(
        self,
        intent_id: str,
        symbol: str,
        side: OrderSide,
        notional: float,
    ) -> BrokerOrder:
        response = self._http_client.post(
            f"{self._base_url}/v2/orders",
            headers=self._headers(),
            json={
                "symbol": _normalize_symbol(symbol),
                "notional": f"{notional:.2f}",
                "side": side,
                "type": "market",
                "time_in_force": "day",
                "client_order_id": intent_id,
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return BrokerOrder(
            intent_id=intent_id,
            broker=self.broker_name,
            environment=self.environment,
            status=str(payload["status"]),
            broker_order_id=str(payload["id"]),
        )

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
        raise ValueError("Alpaca broker secret must include key_id and secret_key")
    return {"key_id": str(key_id), "secret_key": str(secret_key)}


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("symbol must not be empty")
    return normalized
