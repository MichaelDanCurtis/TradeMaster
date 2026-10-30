from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from math import isfinite
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
from tradingagents.ui.models import now_utc
from tradingagents.research.execution_contracts import ExactPaperOrder, ExecutionPolicy
from tradingagents.research.execution_repository import PaperExecutionRepository
from tradingagents.research.execution_service import PaperExecutionService


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
        self,
        run_id: str | None,
        symbol: str,
        side: OrderSide | str,
        notional: float,
        *,
        risk_controls: dict[str, object] | None = None,
    ) -> OrderPreview:
        if not isfinite(notional) or notional <= 0:
            raise ValueError("notional must be greater than zero")
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol must not be empty")
        normalized_side = side.strip().lower()
        if normalized_side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        if run_id is not None:
            self._require_paper_broker_mode(run_id)
        order_side = cast(OrderSide, normalized_side)
        # Snapshot the operator's protective-stop config onto the
        # intent's payload at create time so submit_approved_order can
        # rehydrate it without needing the caller to re-supply.
        intent_payload: dict[str, object] = {}
        if risk_controls:
            intent_payload["risk_controls"] = _normalize_risk_controls(risk_controls)
        execution = self._execution()
        snapshot = self._broker.paper_snapshot()
        estimated_price = self._broker.estimate_price(symbol)
        if not isfinite(estimated_price) or estimated_price <= 0:
            raise ValueError("current quote must be finite and positive")
        limit = Decimal(str(estimated_price)).quantize(Decimal(".01"), rounding=ROUND_UP if order_side == "buy" else ROUND_DOWN)
        quantity = int(Decimal(str(notional)) / limit) if limit else 0
        if quantity < 1:
            raise ValueError("budget cannot cover one whole share; exact paper orders do not round up")
        stop_loss, take_profit, _ = _extract_broker_bracket(intent_payload)
        exact = ExactPaperOrder(symbol=symbol, side=order_side, quantity=quantity, limit_price_usd=limit,
            stop_loss_usd=Decimal(str(stop_loss)) if stop_loss is not None else None,
            take_profit_usd=Decimal(str(take_profit)) if take_profit is not None else None,
            time_in_force="gtc" if stop_loss is not None or take_profit is not None else "day", expires_at=now_utc()+timedelta(minutes=5))
        frozen = execution.repo.preview(None, exact, self._execution_policy(), snapshot, run_id=run_id, budget=notional, intent_payload=intent_payload)
        return OrderPreview(
            intent_id=frozen.intent_id,
            broker=self._broker.broker_name,
            environment=self._broker.environment,
            symbol=symbol,
            side=order_side,
            notional=notional,
            estimated_price=estimated_price,
            estimated_quantity=quantity,
            exact_order=exact.model_dump(mode="json"), order_hash=frozen.content_hash,
            account_id=snapshot.account_id, evidence_kind=snapshot.evidence_kind,
        )

    def approve_order(self, intent_id: str, actor: str, expected_order_hash: str | None = None) -> None:
        intent = self._repo.get_trade_intent(intent_id)
        self._require_paper_broker_mode(intent.run_id)
        execution = self._execution()
        order = execution.repo.for_intent(intent_id)
        if order is None:
            raise PermissionError("Create a fresh exact paper preview before approval")
        execution.repo.approve(order.order_id, actor, expected_order_hash)

    def cancel_order(self, intent_id: str, actor: str) -> str:
        """Cancel locally before dispatch, or await an actual broker cancellation."""
        intent = self._repo.get_trade_intent(intent_id)
        boundary = PaperExecutionRepository(self._repo._session_factory)
        exact = boundary.for_intent(intent_id)
        if exact is None:
            if intent.status != "previewed":
                raise ValueError("Legacy submitted orders require broker reconciliation before cancellation")
            self._repo.record_approval(intent_id, actor, "cancel_order", {"status": intent.status}, {"status": "canceled"})
            return self._repo.mark_trade_intent_status(intent_id, "canceled")
        self._execution().cancel(exact, actor)
        return boundary.for_intent(intent_id).state

    def submit_approved_order(self, intent_id: str) -> BrokerOrder:
        intent = self._repo.get_trade_intent(intent_id)
        self._require_paper_broker_mode(intent.run_id)
        execution = self._execution()
        exact = execution.repo.for_intent(intent_id)
        if exact is None:
            raise PermissionError("A fresh exact paper preview is required; legacy notional approval cannot submit")
        if execution.repo.attempt_for_order(exact.order_id) is None and not self._repo.has_approval(intent_id):
            raise PermissionError("order submission requires approval")
        return self._broker_result(exact, execution.submit(exact))

    def reconcile_order(self, intent_id: str) -> BrokerOrder:
        execution = self._execution()
        exact = execution.repo.for_intent(intent_id)
        if exact is None:
            raise ValueError("No exact paper execution record exists for this intent")
        return self._broker_result(exact, execution.reconcile(exact))

    def execution_history(self, intent_id: str) -> dict:
        self._repo.get_trade_intent(intent_id)
        boundary = PaperExecutionRepository(self._repo._session_factory)
        exact = boundary.for_intent(intent_id)
        if exact is None:
            return {"order": None, "attempt": None, "events": []}
        return {"order": exact, "attempt": boundary.attempt_for_order(exact.order_id), "events": boundary.history(exact.order_id)}

    def _execution(self) -> PaperExecutionService:
        return PaperExecutionService(PaperExecutionRepository(self._repo._session_factory), self._broker)

    def _execution_policy(self) -> ExecutionPolicy:
        policy = self._constraint_policy
        return ExecutionPolicy(
            max_position_fraction=Decimal(str(policy.max_position_percent))/100 if policy else 1,
            max_group_fraction=Decimal(str(policy.max_sector_percent))/100 if policy else 1,
            max_turnover_fraction=Decimal(str(policy.max_daily_turnover_percent))/100 if policy else 2,
            max_drawdown_fraction=Decimal(str(policy.max_drawdown_percent))/100 if policy else 1,
        )

    def _broker_result(self, exact, attempt) -> BrokerOrder:
        return BrokerOrder(intent_id=exact.intent_id, broker=self._broker.broker_name, environment="paper", status=attempt.state,
            broker_order_id=attempt.broker_order_id or "", payload={"exact_order": exact.order, "attempt_id": attempt.attempt_id,
                "observation": attempt.observation, "failure_reason": attempt.failure_reason,
                "evidence_kind": exact.preview_snapshot["evidence_kind"], "account_id": exact.preview_snapshot["account_id"]})

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


# ----------------------------------------------------------------------
# Helpers for the risk_controls plumbing on TradeIntent.payload.
# ----------------------------------------------------------------------


_VALID_RISK_MODES = ("advisory_only", "broker_protective")


def _normalize_risk_controls(raw: dict[str, object]) -> dict[str, object]:
    """Coerce the inbound risk_controls dict to a stable shape.

    The frontend sends ``{stop_loss, take_profit, mode}`` where the
    price legs may be null. We persist them as floats (or None) and
    default mode to ``advisory_only`` so a missing/bad mode never
    accidentally promotes the figures into a live bracket.
    """

    stop_loss = raw.get("stop_loss")
    take_profit = raw.get("take_profit")
    mode = str(raw.get("mode") or "advisory_only")
    if mode not in _VALID_RISK_MODES:
        mode = "advisory_only"
    normalized: dict[str, object] = {
        "stop_loss": float(stop_loss) if stop_loss is not None else None,
        "take_profit": float(take_profit) if take_profit is not None else None,
        "mode": mode,
    }
    return normalized


def _extract_broker_bracket(
    payload: dict[str, object] | None,
) -> tuple[float | None, float | None, str]:
    """Return ``(stop_loss, take_profit, mode)`` from a stored intent payload.

    Returns ``(None, None, "advisory_only")`` for any intent that did
    not opt into ``broker_protective`` — that's the safe legacy path
    where the figures stay informational and the broker sees a plain
    market order.
    """

    if not payload:
        return None, None, "advisory_only"
    controls = payload.get("risk_controls")
    if not isinstance(controls, dict):
        return None, None, "advisory_only"
    mode = str(controls.get("mode") or "advisory_only")
    if mode != "broker_protective":
        return None, None, mode
    raw_stop = controls.get("stop_loss")
    raw_take = controls.get("take_profit")
    stop_loss = float(raw_stop) if isinstance(raw_stop, (int, float)) else None
    take_profit = float(raw_take) if isinstance(raw_take, (int, float)) else None
    return stop_loss, take_profit, mode
