from __future__ import annotations

from uuid import uuid4

from tradingagents.ui.brokers.base import BrokerOrder, OrderSide


class FakePaperBroker:
    broker_name = "fake"
    environment = "paper"

    def estimate_price(self, symbol: str) -> float:
        return {
            "NVDA": 900.0,
            "AAPL": 190.0,
            "MSFT": 420.0,
            "SPY": 520.0,
        }.get(symbol.upper(), 100.0)

    def submit_order(
        self, intent_id: str, symbol: str, side: OrderSide, notional: float
    ) -> BrokerOrder:
        return BrokerOrder(
            intent_id=intent_id,
            broker=self.broker_name,
            environment=self.environment,
            status="submitted",
            broker_order_id=f"fake_order_{uuid4().hex[:12]}",
        )
