from __future__ import annotations

from collections.abc import Callable
from typing import cast

from tradingagents.ui.brokers.base import (
    BrokerAdapter,
    BrokerOrder,
    OrderPreview,
    OrderSide,
)
from tradingagents.ui.constraints import (
    ConstraintContext,
    PortfolioConstraintPolicy,
    SymbolicConstraintEngine,
    TradeProposal,
)
from tradingagents.ui.repository import UiRepository


class BrokerService:
    def __init__(
        self,
        repository: UiRepository,
        broker: BrokerAdapter,
        *,
        constraint_engine: SymbolicConstraintEngine | None = None,
        constraint_policy: PortfolioConstraintPolicy | None = None,
        constraint_context_provider: Callable[[str, str], ConstraintContext] | None = None,
    ) -> None:
        self._repo = repository
        self._broker = broker
        self._constraint_engine = constraint_engine
        self._constraint_policy = constraint_policy
        self._constraint_context_provider = constraint_context_provider

    def preview_order(
        self, run_id: str, symbol: str, side: OrderSide | str, notional: float
    ) -> OrderPreview:
        if notional <= 0:
            raise ValueError("notional must be greater than zero")
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol must not be empty")
        normalized_side = side.strip().lower()
        if normalized_side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        self._require_paper_broker_mode(run_id)
        order_side = cast(OrderSide, normalized_side)
        self._require_symbolic_constraints(
            run_id=run_id,
            symbol=symbol,
            side=order_side,
            notional=notional,
        )
        intent = self._repo.create_trade_intent(
            run_id=run_id,
            symbol=symbol,
            side=order_side,
            notional=notional,
        )
        estimated_price = self._broker.estimate_price(symbol)
        return OrderPreview(
            intent_id=intent.intent_id,
            broker=self._broker.broker_name,
            environment=self._broker.environment,
            symbol=symbol,
            side=order_side,
            notional=notional,
            estimated_price=estimated_price,
            estimated_quantity=round(notional / estimated_price, 6),
        )

    def approve_order(self, intent_id: str, actor: str) -> None:
        intent = self._repo.get_trade_intent(intent_id)
        self._require_paper_broker_mode(intent.run_id)
        self._repo.record_approval(
            intent_id=intent_id,
            actor=actor,
            action="approve_order",
            before_payload={"status": intent.status},
            after_payload={"status": "approved"},
        )

    def submit_approved_order(self, intent_id: str) -> BrokerOrder:
        intent = self._repo.get_trade_intent(intent_id)
        self._require_paper_broker_mode(intent.run_id)
        if intent.status != "previewed":
            raise ValueError(f"order is not previewed; current status is {intent.status}")
        if not self._repo.has_approval(intent_id):
            raise PermissionError("order submission requires approval")
        if intent.side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        order_side = cast(OrderSide, intent.side)
        order = self._broker.submit_order(
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            side=order_side,
            notional=intent.notional,
        )
        self._repo.store_broker_order(
            intent_id=order.intent_id,
            broker=order.broker,
            environment=order.environment,
            status=order.status,
            broker_order_id=order.broker_order_id,
        )
        return order

    def _require_paper_broker_mode(self, run_id: str) -> None:
        config = self._repo.get_run_config(run_id)
        if config.get("broker_mode") != "paper":
            raise PermissionError("paper broker requires broker_mode=paper")

    def _require_symbolic_constraints(
        self,
        *,
        run_id: str,
        symbol: str,
        side: OrderSide,
        notional: float,
    ) -> None:
        if (
            self._constraint_engine is None
            or self._constraint_policy is None
            or self._constraint_context_provider is None
        ):
            return
        decision = self._constraint_engine.evaluate(
            TradeProposal(
                symbol=symbol,
                side=side,
                notional=notional,
                environment=self._broker.environment,
            ),
            self._constraint_context_provider(run_id, symbol),
            self._constraint_policy,
        )
        if not decision.passed:
            rules = ", ".join(violation.rule for violation in decision.violations)
            raise PermissionError(f"symbolic constraints vetoed order: {rules}")
