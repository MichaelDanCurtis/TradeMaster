from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field


BarTimeframe = Literal["1Min", "5Min", "15Min", "1Hour", "1Day"]


class MarketDataBar(BaseModel):
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float | None = None
    trade_count: int | None = None


class MarketDataQuote(BaseModel):
    symbol: str
    timestamp: datetime
    bid_price: float
    bid_size: int = Field(ge=0)
    ask_price: float
    ask_size: int = Field(ge=0)


class MarketDataProvider(Protocol):
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
        ...

    def latest_quote(self, symbol: str, *, feed: str | None = None) -> MarketDataQuote:
        ...
