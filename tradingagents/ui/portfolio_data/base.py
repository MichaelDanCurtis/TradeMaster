from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel


class PortfolioAccount(BaseModel):
    account_id: str
    name: str
    official_name: str | None = None
    type: str
    subtype: str | None = None
    mask: str | None = None
    current_balance: float | None = None
    iso_currency_code: str | None = None


class PortfolioHolding(BaseModel):
    account_id: str
    security_id: str
    symbol: str | None = None
    name: str | None = None
    quantity: float
    price: float | None = None
    value: float | None = None
    cost_basis: float | None = None


class PortfolioTransaction(BaseModel):
    transaction_id: str
    account_id: str
    date: date
    name: str
    amount: float
    iso_currency_code: str | None = None
    categories: list[str]


class PortfolioProvider(Protocol):
    def accounts(self) -> list[PortfolioAccount]:
        ...

    def holdings(self) -> list[PortfolioHolding]:
        ...

    def transactions(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> list[PortfolioTransaction]:
        ...
