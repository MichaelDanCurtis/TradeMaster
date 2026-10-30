from __future__ import annotations

from uuid import uuid4
from decimal import Decimal as D

from tradingagents.research.execution_contracts import AccountPosition, ExactPaperOrder, OpenPaperOrder, PaperAccountSnapshot, PaperOrderObservation, TERMINAL
from tradingagents.ui.models import now_utc
from tradingagents.research.accounting_contracts import AccountActivity, AccountActivityBatch

from tradingagents.ui.brokers.base import BrokerOrder, OrderSide


class FakePaperBroker:
    broker_name = "fake"
    environment = "paper"

    def __init__(self, *, cash_usd="100000", positions=None):
        self.cash_usd = D(cash_usd)
        self.positions = {p.symbol: p for p in (positions or [])}
        self.exact_orders = {}
        self.observations = {}
        self.economic_orders = 0
        self.turnover = D(0)
        self.activities = []
        self.peak = self.cash_usd + sum((p.market_value_usd for p in self.positions.values()), D(0))

    def paper_snapshot(self) -> PaperAccountSnapshot:
        at = now_utc()
        equity = self.cash_usd + sum((p.market_value_usd for p in self.positions.values()), D(0))
        self.peak = max(self.peak, equity)
        orders = [OpenPaperOrder(client_order_id=identifier, broker_order_id=row.broker_order_id, symbol=row.symbol, side=row.side,
            remaining_quantity=D(row.quantity)-row.filled_quantity, maximum_price_usd=self.exact_orders[identifier].limit_price_usd)
            for identifier, row in self.observations.items() if row.status not in TERMINAL]
        committed = sum((o.remaining_quantity*o.maximum_price_usd for o in orders if o.side == "buy"), D(0))
        return PaperAccountSnapshot(provider_id="fake", account_id="fixture-paper-account", evidence_kind="fixture", started_at=at, observed_at=at,
            equity_usd=equity, cash_usd=self.cash_usd, buying_power_usd=max(D(0), self.cash_usd-committed), daily_turnover_usd=self.turnover,
            drawdown_fraction=max(D(0), 1-equity/self.peak) if self.peak else None, trading_blocked=False, positions=list(self.positions.values()), open_orders=orders, complete=True,
            limitations=["In-memory execution fixture, not a broker account or investment evidence"])

    def submit_exact_order(self, client_order_id: str, order: ExactPaperOrder) -> PaperOrderObservation:
        if client_order_id in self.observations:
            if self.exact_orders[client_order_id] != order:
                raise ValueError("Client order ID is already bound to another exact order")
            return self.observations[client_order_id]
        self.economic_orders += 1
        self.exact_orders[client_order_id] = order.model_copy(deep=True)
        observation = PaperOrderObservation(client_order_id=client_order_id, broker_order_id=f"fake_order_{uuid4().hex[:12]}", symbol=order.symbol,
            side=order.side, quantity=order.quantity, filled_quantity=0, average_fill_price_usd=None, status="accepted", observed_at=now_utc())
        self.observations[client_order_id] = observation
        return observation

    def find_order(self, client_order_id: str) -> PaperOrderObservation | None:
        return self.observations.get(client_order_id)

    def cancel_exact_order(self, client_order_id: str) -> PaperOrderObservation | None:
        current = self.observations.get(client_order_id)
        if current and current.status not in TERMINAL:
            current = current.model_copy(update={"status": "canceled", "observed_at": now_utc()})
            self.observations[client_order_id] = current
        return current

    def fill(self, client_order_id: str, quantity: int, price=None) -> PaperOrderObservation:
        current = self.observations[client_order_id]
        order = self.exact_orders[client_order_id]
        if current.status in TERMINAL or quantity <= 0 or current.filled_quantity + quantity > order.quantity:
            raise ValueError("Invalid fixture fill")
        value = D(str(price if price is not None else order.limit_price_usd))
        position = self.positions.get(order.symbol)
        old_quantity = position.quantity if position else D(0)
        next_quantity = old_quantity + quantity * (1 if order.side == "buy" else -1)
        if next_quantity < 0:
            raise ValueError("Fixture reduction would create a short")
        basis = (position.cost_basis_usd if position else D(0))
        next_basis = basis + quantity*value if order.side == "buy" else basis*next_quantity/old_quantity
        # Broker-facing money has finite precision. Divide only after multiplying
        # and round the remaining average basis to the account contract scale.
        next_basis = next_basis.quantize(D(".000001"))
        self.positions[order.symbol] = AccountPosition(symbol=order.symbol, quantity=next_quantity, market_value_usd=next_quantity*value, cost_basis_usd=next_basis, risk_group=order.risk_group)
        self.cash_usd += quantity*value * (-1 if order.side == "buy" else 1)
        self.turnover += quantity*value
        total = current.filled_quantity + quantity
        average = ((current.average_fill_price_usd or D(0))*current.filled_quantity + quantity*value)/total
        current = current.model_copy(update={"filled_quantity": total, "average_fill_price_usd": average, "status": "filled" if total == order.quantity else "partially_filled", "observed_at": now_utc()})
        self.observations[client_order_id] = current
        self.activities.append(AccountActivity(source_id="fixture_fill_"+uuid4().hex, kind="fill", effective_at=current.observed_at,
            symbol=order.symbol, side=order.side, quantity=quantity, price_usd=value, broker_order_id=current.broker_order_id))
        return current

    def account_activities(self, start, until):
        return AccountActivityBatch(provider_id="fake", account_id="fixture-paper-account", evidence_kind="fixture", source="in_memory_fixture",
            coverage_start=start, coverage_end=until, observed_at=now_utc(), complete=True,
            activities=[a for a in self.activities if start < a.effective_at <= until])

    def estimate_price(self, symbol: str) -> float:
        return {
            "NVDA": 900.0,
            "AAPL": 190.0,
            "MSFT": 420.0,
            "SPY": 520.0,
        }.get(symbol.upper(), 100.0)

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
        # Match the alpaca adapter shape — when a bracket / OTO is
        # requested we round-trip the legs in the BrokerOrder payload
        # so the ladder UI can render them in fake-broker test runs.
        payload: dict[str, object] = {}
        if stop_loss is not None or take_profit is not None:
            payload["bracket"] = {
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            }
        return BrokerOrder(
            intent_id=intent_id,
            broker=self.broker_name,
            environment=self.environment,
            status="submitted",
            broker_order_id=f"fake_order_{uuid4().hex[:12]}",
            payload=payload,
        )
