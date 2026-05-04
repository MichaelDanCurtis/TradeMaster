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
    def json(self) -> dict[str, Any]: ...

    def raise_for_status(self) -> None: ...


class HttpClient(Protocol):
    def post(
        self,
        url: str,
        *,
        json: dict[str, object],
        timeout: float,
    ) -> HttpResponse:
        ...


class PlaidPortfolioProvider:
    def __init__(
        self,
        *,
        secret_store: SecretStore,
        secret_ref: str,
        http_client: HttpClient | None = None,
        base_url: str = "https://production.plaid.com",
        timeout: float = 15.0,
    ) -> None:
        self._secret_store = secret_store
        self._secret_ref = secret_ref
        self._http_client = http_client or requests
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def accounts(self) -> list[PortfolioAccount]:
        payload = self._post("/accounts/balance/get", {})
        return [_account_from_plaid(account) for account in payload.get("accounts", [])]

    def holdings(self) -> list[PortfolioHolding]:
        payload = self._post("/investments/holdings/get", {})
        securities = {
            security["security_id"]: security
            for security in payload.get("securities", [])
            if "security_id" in security
        }
        return [
            _holding_from_plaid(holding, securities.get(holding.get("security_id")))
            for holding in payload.get("holdings", [])
        ]

    def transactions(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[PortfolioTransaction]:
        payload = self._post(
            "/transactions/get",
            {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )
        return [
            _transaction_from_plaid(transaction)
            for transaction in payload.get("transactions", [])
        ]

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        response = self._http_client.post(
            f"{self._base_url}{path}",
            json={
                **self._credentials(),
                **payload,
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def _credentials(self) -> dict[str, str]:
        payload = json.loads(self._secret_store.get_secret(self._secret_ref))
        client_id = payload.get("client_id")
        secret = payload.get("secret")
        access_token = payload.get("access_token")
        if not client_id or not secret or not access_token:
            raise ValueError(
                "Plaid secret must include client_id, secret, and access_token"
            )
        return {
            "client_id": str(client_id),
            "secret": str(secret),
            "access_token": str(access_token),
        }


def _account_from_plaid(account: Mapping[str, Any]) -> PortfolioAccount:
    balances = account.get("balances") or {}
    return PortfolioAccount(
        account_id=str(account["account_id"]),
        name=str(account["name"]),
        official_name=account.get("official_name"),
        type=str(account["type"]),
        subtype=account.get("subtype"),
        mask=account.get("mask"),
        current_balance=(
            float(balances["current"]) if balances.get("current") is not None else None
        ),
        iso_currency_code=balances.get("iso_currency_code"),
    )


def _holding_from_plaid(
    holding: Mapping[str, Any],
    security: Mapping[str, Any] | None,
) -> PortfolioHolding:
    return PortfolioHolding(
        account_id=str(holding["account_id"]),
        security_id=str(holding["security_id"]),
        symbol=str(security.get("ticker_symbol")) if security else None,
        name=str(security.get("name")) if security else None,
        quantity=float(holding["quantity"]),
        price=(
            float(holding["institution_price"])
            if holding.get("institution_price") is not None
            else None
        ),
        value=(
            float(holding["institution_value"])
            if holding.get("institution_value") is not None
            else None
        ),
        cost_basis=(
            float(holding["cost_basis"])
            if holding.get("cost_basis") is not None
            else None
        ),
    )


def _transaction_from_plaid(transaction: Mapping[str, Any]) -> PortfolioTransaction:
    return PortfolioTransaction(
        transaction_id=str(transaction["transaction_id"]),
        account_id=str(transaction["account_id"]),
        date=date.fromisoformat(str(transaction["date"])),
        name=str(transaction["name"]),
        amount=float(transaction["amount"]),
        iso_currency_code=transaction.get("iso_currency_code"),
        categories=[str(category) for category in transaction.get("category", [])],
    )
