from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from tradingagents.research.execution_contracts import ExactPaperOrder, PaperAccountSnapshot, PaperOrderObservation


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
    exact_order: dict[str, Any] | None = None
    order_hash: str | None = None
    account_id: str | None = None
    evidence_kind: str | None = None


@dataclass(frozen=True)
class BrokerOrder:
    intent_id: str
    broker: str
    environment: str
    status: str
    broker_order_id: str
    # Optional structured payload — used to round-trip bracket leg pricing
    # and any error detail the broker returned so the UI can inspect it.
    payload: dict[str, Any] = field(default_factory=dict)


class BrokerAdapter(Protocol):
    broker_name: str
    environment: str

    def estimate_price(self, symbol: str) -> float:
        ...

    def paper_snapshot(self) -> PaperAccountSnapshot: ...

    def submit_exact_order(self, client_order_id: str, order: ExactPaperOrder) -> PaperOrderObservation: ...

    def find_order(self, client_order_id: str) -> PaperOrderObservation | None: ...

    def cancel_exact_order(self, client_order_id: str) -> PaperOrderObservation | None: ...

    def submit_order(
        self,
        intent_id: str,
        symbol: str,
        side: OrderSide,
        notional: float,
        *,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> BrokerOrder:
        ...
