"""
Alpaca portfolio data provider.

Read-side companion to ``brokers/alpaca.py``. Pulls account snapshot, current
positions, and closed orders via Alpaca's REST API. Reuses the same secret
shape as the broker adapter: a JSON blob containing ``key_id`` + ``secret_key``,
stored as a single ``secret_ref`` in the configured ``SecretStore``.

Only GET endpoints are exposed; this provider has no write surface.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from typing import Any, Protocol

import requests

from tradingagents.ui.portfolio_data.base import (
    PortfolioAccount,
    PortfolioHolding,
    PortfolioTransaction,
)
from tradingagents.ui.secrets import SecretStore


class HttpResponse(Protocol):
    def json(self) -> Any: ...

    def raise_for_status(self) -> None: ...


class HttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
        timeout: float,
    ) -> HttpResponse:
        ...


class AlpacaPortfolioProvider:
    """Read-only portfolio adapter against Alpaca's paper or live REST API."""

    def __init__(
        self,
        *,
        secret_store: SecretStore,
        secret_ref: str,
        http_client: HttpClient | None = None,
        base_url: str = "https://paper-api.alpaca.markets",
        timeout: float = 15.0,
    ) -> None:
        self._secret_store = secret_store
        self._secret_ref = secret_ref
        self._http_client = http_client or requests
        self._base_url = base_url.rstrip("/").removesuffix("/v2")
        self._timeout = timeout

    def accounts(self) -> list[PortfolioAccount]:
        payload = self._get("/v2/account")
        if not isinstance(payload, Mapping):
            return []
        return [_account_from_alpaca(payload)]

    def holdings(self) -> list[PortfolioHolding]:
        payload = self._get("/v2/positions")
        if not isinstance(payload, list):
            return []
        return [_holding_from_alpaca(position) for position in payload]

    def transactions(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[PortfolioTransaction]:
        payload = self._get(
            "/v2/orders",
            params={
                "status": "closed",
                "after": start_date.isoformat(),
                "until": end_date.isoformat(),
                "limit": "100",
                "direction": "desc",
            },
        )
        if not isinstance(payload, list):
            return []
        return [
            _transaction_from_alpaca(order)
            for order in payload
            if isinstance(order, Mapping)
        ]

    def _get(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        response = self._http_client.get(
            f"{self._base_url}{path}",
            headers=self._headers(),
            params=params,
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
        raise ValueError("Alpaca portfolio secret must include key_id and secret_key")
    return {"key_id": str(key_id), "secret_key": str(secret_key)}


def _maybe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _account_from_alpaca(account: Mapping[str, Any]) -> PortfolioAccount:
    # Alpaca's account object exposes cash, buying_power, equity, etc. We surface
    # equity as `current_balance` since that's the closest analogue to Plaid's
    # account balance — it's the most useful single number for the UI.
    equity = _maybe_float(account.get("equity"))
    return PortfolioAccount(
        account_id=str(account.get("id") or account.get("account_number") or "alpaca-account"),
        name="Alpaca Paper" if str(account.get("status", "")).upper() == "ACTIVE" else str(account.get("status", "Alpaca account")),
        official_name=str(account.get("account_number") or "") or None,
        type="brokerage",
        subtype="paper" if "paper" in str(account.get("trade_suspended_by_user", "")).lower() else None,
        mask=str(account.get("account_number") or "")[-4:] if account.get("account_number") else None,
        current_balance=equity,
        iso_currency_code=str(account.get("currency") or "USD"),
    )


def _holding_from_alpaca(position: Mapping[str, Any]) -> PortfolioHolding:
    qty = _maybe_float(position.get("qty")) or 0.0
    return PortfolioHolding(
        account_id="alpaca-account",
        security_id=str(position.get("asset_id") or position.get("symbol") or ""),
        symbol=str(position.get("symbol") or "") or None,
        name=str(position.get("exchange") or "") or None,
        quantity=qty,
        price=_maybe_float(position.get("current_price")),
        value=_maybe_float(position.get("market_value")),
        cost_basis=_maybe_float(position.get("cost_basis")),
    )


def _transaction_from_alpaca(order: Mapping[str, Any]) -> PortfolioTransaction:
    filled_at = order.get("filled_at") or order.get("submitted_at") or order.get("created_at")
    try:
        parsed_date = date.fromisoformat(str(filled_at)[:10])
    except (TypeError, ValueError):
        parsed_date = date.today()

    filled_qty = _maybe_float(order.get("filled_qty")) or 0.0
    filled_avg_price = _maybe_float(order.get("filled_avg_price")) or 0.0
    side = str(order.get("side") or "")
    # Convention: buys are negative cash flow (money out), sells positive.
    signed_amount = filled_qty * filled_avg_price * (-1.0 if side == "buy" else 1.0)

    return PortfolioTransaction(
        transaction_id=str(order.get("id") or ""),
        account_id="alpaca-account",
        date=parsed_date,
        name=f"{side.upper()} {order.get('symbol', '')} {filled_qty} @ {filled_avg_price}".strip(),
        amount=signed_amount,
        iso_currency_code="USD",
        categories=[side, str(order.get("order_type") or "market")],
    )
