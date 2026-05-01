from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


OrderSide = Literal["buy", "sell"]


@dataclass(frozen=True)
class OrderPreview:
    intent_id: str
    broker: str
    environment: str
    symbol: str
    side: OrderSide
    notional: float
    estimated_price: float
    estimated_quantity: float


@dataclass(frozen=True)
class BrokerOrder:
    intent_id: str
    broker: str
    environment: str
    status: str
    broker_order_id: str


class BrokerAdapter(Protocol):
    broker_name: str
    environment: str

    def estimate_price(self, symbol: str) -> float:
        ...

    def submit_order(
        self, intent_id: str, symbol: str, side: OrderSide, notional: float
    ) -> BrokerOrder:
        ...
