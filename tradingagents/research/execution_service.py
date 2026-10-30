"""Broker calls occur only after an exact approval and durable claim."""
from tradingagents.research.execution_contracts import ExactPaperOrder, TERMINAL
from tradingagents.research.execution_repository import PaperExecutionRepository, account_key
from tradingagents.research.repository import ConflictError


class PaperExecutionService:
    def __init__(self, repository: PaperExecutionRepository, broker):
        self.repo, self.broker = repository, broker
        if broker.environment != "paper" or not all(callable(getattr(broker, name, None)) for name in ("paper_snapshot", "submit_exact_order", "find_order", "cancel_exact_order")):
            raise PermissionError("Broker lacks the exact paper execution and reconciliation capability")

    def submit(self, order):
        existing = self.repo.attempt_for_order(order.order_id)
        if existing:
            return self.reconcile(order) if existing.state not in TERMINAL else existing
        snapshot = self.bound_snapshot(order)
        from tradingagents.scheduling.calendar import check_dispatch
        check_dispatch(self.repo.sessions, order, self.broker, snapshot)
        attempt, claimed = self.repo.claim(order.order_id, snapshot)
        if not claimed:
            return self.reconcile(order)
        try:
            observation = self.broker.submit_exact_order(attempt.client_order_id, ExactPaperOrder.model_validate(order.order))
            return self.repo.observe(attempt.attempt_id, observation)
        except Exception as exc:
            # Even HTTP failures are ambiguous unless the broker adapter returns
            # a validated definitive rejection. Never retry a POST here.
            return self.repo.unknown(attempt.attempt_id, f"Submission outcome unknown ({type(exc).__name__}); reconcile by client order ID before any new entry")

    def reconcile(self, order):
        self.bound_identity(order)
        attempt = self.repo.attempt_for_order(order.order_id)
        if attempt is None:
            raise ConflictError("Order has no submission attempt to reconcile")
        try:
            observation = self.broker.find_order(attempt.client_order_id)
            if observation is None:
                return self.repo.unknown(attempt.attempt_id, "Client order ID is not yet observed at the broker; absence is not proof of rejection and no POST was retried")
            return self.repo.observe(attempt.attempt_id, observation)
        except Exception as exc:
            return self.repo.unknown(attempt.attempt_id, f"Broker reconciliation unavailable ({type(exc).__name__}); reservation retained")

    def cancel(self, order, actor):
        self.bound_identity(order)
        attempt = self.repo.request_cancel(order.order_id, actor)
        if attempt is None or attempt.state in TERMINAL:
            return attempt
        try:
            observation = self.broker.cancel_exact_order(attempt.client_order_id)
            if observation is not None:
                return self.repo.observe(attempt.attempt_id, observation)
        except Exception:
            pass
        # Cancellation may have reached the broker. Keep its last observed
        # state and reservation; caller displays pending_cancel separately.
        return attempt

    def bound_snapshot(self, order):
        snapshot = self.broker.paper_snapshot()
        if account_key(snapshot) != order.account_key:
            raise ConflictError("Configured broker account differs from the approved account")
        return snapshot

    def bound_identity(self, order):
        # Read-only recovery and cancellation must not depend on usable risk
        # history or a currently tradable account. Identity must still match.
        identity = self.broker.paper_identity() if callable(getattr(self.broker, "paper_identity", None)) else self.broker.paper_snapshot()
        if account_key(identity) != order.account_key:
            raise ConflictError("Configured broker account differs from the approved account")
        return identity
