"""One durable paper submission boundary for manual and deployment intents."""
from contextlib import nullcontext
from datetime import timedelta
from decimal import Decimal as D

from sqlalchemy import text
from sqlmodel import select

from tradingagents.research.contracts import content_hash
from tradingagents.research.execution_contracts import ExactPaperOrder, ExecutionPolicy, PaperAccountSnapshot, PaperOrderObservation, TERMINAL
from tradingagents.research.execution_models import (
    ExactPaperOrderRecord, PaperExecutionAccountRecord, PaperExecutionAttemptRecord,
    PaperExecutionEventRecord, PaperReservationRecord,
)
from tradingagents.research.repository import ConflictError, ResearchRepository, require
from tradingagents.ui.models import ApprovalLedgerRecord, ApprovalRecord, BrokerOrderRecord, TradeIntentRecord, RunRecord, now_utc


def account_key(snapshot: PaperAccountSnapshot) -> str:
    return content_hash({"provider": snapshot.provider_id, "account": snapshot.account_id, "environment": snapshot.environment})


def require_fresh(snapshot: PaperAccountSnapshot, policy: ExecutionPolicy) -> None:
    now = now_utc()
    if not snapshot.complete or snapshot.trading_blocked:
        raise ConflictError("Paper account facts are incomplete or trading is blocked")
    if snapshot.equity_usd <= 0:
        raise ConflictError("Paper execution requires positive current account equity")
    if snapshot.observed_at > now + timedelta(seconds=1) or snapshot.started_at < now - timedelta(seconds=policy.snapshot_max_age_seconds):
        raise ConflictError("Paper account snapshot is stale or future-dated")


def risk_check(snapshot: PaperAccountSnapshot, order: ExactPaperOrder, policy: ExecutionPolicy, reservations: list[PaperReservationRecord], attempts: dict) -> None:
    require_fresh(snapshot, policy)
    position = next((p for p in snapshot.positions if p.symbol == order.symbol), None)
    remote_ids = {o.client_order_id for o in snapshot.open_orders}
    local = [r for r in reservations if attempts[r.attempt_id].client_order_id not in remote_ids]
    pending = [(o.symbol, o.side, o.remaining_quantity, o.maximum_price_usd, o.risk_group) for o in snapshot.open_orders]
    pending.extend((r.symbol, r.side, D(r.quantity), D(r.price_usd), r.risk_group) for r in local)
    if order.side == "sell":
        reserved_shares = sum((q for symbol, side, q, _, _ in pending if symbol == order.symbol and side == "sell"), D(0))
        if order.quantity + reserved_shares > (position.quantity if position else 0):
            raise ConflictError("Reduction exceeds unreserved current holdings; no short sale is permitted")
        # A funded reduction remains possible during a drawdown/turnover pause.
        # It still needs exact approval, fresh holdings and a reservation.
        if order.fee_reserve_usd > snapshot.cash_usd:
            raise ConflictError("Cash cannot cover the reduction's fee reserve")
        return
    if any(attempts[r.attempt_id].state in {"dispatching", "unknown"} for r in reservations):
        raise ConflictError("An unresolved paper submission blocks new entries")
    if snapshot.drawdown_fraction is None:
        raise ConflictError("Reconciled account drawdown is unavailable; new entries are blocked")
    if snapshot.drawdown_fraction >= policy.max_drawdown_fraction:
        raise ConflictError("Drawdown intervention blocks new entries; reductions remain reviewable")
    if any(price is None and q > 0 for _, _, q, price, _ in pending):
        raise ConflictError("An open order has no bounded price; pending exposure or turnover is unknown")
    buys = [(symbol, q*price, group) for symbol, side, q, price, group in pending if side == "buy" and q > 0]
    local_cash = sum((D(r.quantity)*D(r.price_usd)+D(r.fee_usd) for r in local if r.side == "buy"), D(0))
    pending_cash = sum((amount for _, amount, _ in buys), D(0)) + sum((D(r.fee_usd) for r in reservations if r.side == "buy"), D(0))
    cost = order.maximum_notional_usd + order.fee_reserve_usd
    if cost > snapshot.buying_power_usd - local_cash or cost > snapshot.cash_usd - pending_cash - snapshot.equity_usd*policy.cash_reserve_fraction:
        raise ConflictError("Cash/buying power is already committed or below the reserve")
    market_value = sum((p.market_value_usd for p in snapshot.positions), D(0))
    if market_value + pending_cash + cost > snapshot.equity_usd:
        raise ConflictError("Final total exposure would require leverage")
    same = sum((amount for symbol, amount, _ in buys if symbol == order.symbol), D(0))
    if (position.market_value_usd if position else 0) + same + order.maximum_notional_usd > snapshot.equity_usd * policy.max_position_fraction:
        raise ConflictError("Final position concentration exceeds policy")
    # Unknown group classifications count against every candidate group;
    # they never turn into favorable zero exposure.
    group_value = sum((p.market_value_usd for p in snapshot.positions if p.risk_group is None or order.risk_group is None or p.risk_group == order.risk_group), D(0))
    group_pending = sum((amount for _, amount, group in buys if group is None or order.risk_group is None or group == order.risk_group), D(0))
    if group_value + group_pending + order.maximum_notional_usd > snapshot.equity_usd * policy.max_group_fraction:
        raise ConflictError("Final risk-group exposure exceeds policy")
    pending_turnover = sum((q*price for _, _, q, price, _ in pending if price is not None), D(0))
    if snapshot.daily_turnover_usd + pending_turnover + order.maximum_notional_usd > snapshot.equity_usd * policy.max_turnover_fraction:
        raise ConflictError("Daily executed and pending turnover exceeds policy")


class PaperExecutionRepository(ResearchRepository):
    def for_intent(self, intent_id: str) -> ExactPaperOrderRecord | None:
        with self.sessions() as session:
            return session.exec(select(ExactPaperOrderRecord).where(ExactPaperOrderRecord.intent_id == intent_id)).first()

    def attempt_for_order(self, order_id: str) -> PaperExecutionAttemptRecord | None:
        with self.sessions() as session:
            return session.exec(select(PaperExecutionAttemptRecord).where(PaperExecutionAttemptRecord.order_id == order_id)).first()

    def history(self, order_id: str) -> list[PaperExecutionEventRecord]:
        with self.sessions() as session:
            require(session, ExactPaperOrderRecord, order_id)
            return list(session.exec(select(PaperExecutionEventRecord).where(PaperExecutionEventRecord.order_id == order_id).order_by(PaperExecutionEventRecord.created_at)))

    def preview(self, intent_id: str | None, order: ExactPaperOrder, policy: ExecutionPolicy, snapshot: PaperAccountSnapshot, *, deployment_id: str | None = None, target_id: str | None = None, run_id: str | None = None, budget=None, intent_payload=None, session=None) -> ExactPaperOrderRecord:
        require_fresh(snapshot, policy)
        if order.expires_at <= now_utc():
            raise ConflictError("Exact order has already expired")
        key = account_key(snapshot)
        digest = content_hash({"account_key": key, "order": order.model_dump(mode="json"), "policy": policy.model_dump(mode="json"), "deployment_id": deployment_id, "target_id": target_id})
        with (self.transaction() if session is None else nullcontext(session)) as session:
            if target_id is not None:
                previous_target=session.exec(select(ExactPaperOrderRecord).where(ExactPaperOrderRecord.target_id==target_id)).first()
                if previous_target:
                    if previous_target.content_hash!=digest or (intent_id is not None and previous_target.intent_id!=intent_id):
                        raise ConflictError("Deployment target already has a different exact order")
                    return previous_target
            if intent_id is None:
                if run_id is None:
                    # Bookkeeping for a manual ticket, not a research task. This
                    # transaction rolls it back if any order/risk check fails.
                    context = RunRecord(ticker=order.symbol, trade_date=now_utc().date().isoformat(),
                        status="completed", config={"purpose":"manual_order", "broker_mode":"paper",
                        "execution_mode":"real", "analysts":[]})
                    session.add(context)
                    session.flush()
                    run_id = context.run_id
                require(session, RunRecord, run_id)
                intent = TradeIntentRecord(run_id=run_id, symbol=order.symbol, side=order.side, notional=float(budget), order_type="limit", payload=intent_payload or {})
                session.add(intent)
                session.flush()
                intent_id = intent.intent_id
            else:
                intent = require(session, TradeIntentRecord, intent_id)
            if require(session, RunRecord, intent.run_id).config.get("broker_mode") != "paper":
                raise ConflictError("Exact execution requires broker_mode=paper")
            if intent.symbol != order.symbol or intent.side != order.side or D(str(intent.notional)) < order.maximum_notional_usd + order.fee_reserve_usd:
                raise ConflictError("Exact order differs from its intent or exceeds its budget")
            existing = session.exec(select(ExactPaperOrderRecord).where(ExactPaperOrderRecord.intent_id == intent_id)).first()
            if existing:
                if existing.content_hash != digest:
                    raise ConflictError("An exact preview is immutable; create a new intent")
                return existing
            account = session.get(PaperExecutionAccountRecord, key)
            if account is None:
                account = PaperExecutionAccountRecord(account_key=key, provider_id=snapshot.provider_id, account_id=snapshot.account_id, snapshot=snapshot.model_dump(mode="json"))
                session.add(account)
                session.flush()
            reservations, attempts = self._pending(session, key)
            risk_check(snapshot, order, policy, reservations, attempts)
            from tradingagents.research.deployment_repository import check_deployment_order
            check_deployment_order(session, deployment_id, target_id, snapshot, order, policy)
            record = ExactPaperOrderRecord(intent_id=intent_id, account_key=key, deployment_id=deployment_id, target_id=target_id,
                content_hash=digest, order=order.model_dump(mode="json"), policy=policy.model_dump(mode="json"), preview_snapshot=snapshot.model_dump(mode="json"))
            session.add(record)
            session.flush()
            self._execution_event(session, record, "previewed", {"order_hash": digest})
        return record

    def approve(self, order_id: str, actor: str, expected_hash: str | None = None, *, session=None, schedule_approval=False) -> ExactPaperOrderRecord:
        with (self.transaction() if session is None else nullcontext(session)) as session:
            order = require(session, ExactPaperOrderRecord, order_id)
            from tradingagents.scheduling.repository import require_schedule_approval
            require_schedule_approval(session, order.order_id, schedule_approval)
            exact = ExactPaperOrder.model_validate(order.order)
            intent = require(session, TradeIntentRecord, order.intent_id)
            if require(session, RunRecord, intent.run_id).config.get("broker_mode") != "paper":
                raise ConflictError("Exact approval requires broker_mode=paper")
            if order.state not in {"previewed", "approved"} or exact.expires_at <= now_utc():
                raise ConflictError("Exact preview is expired or no longer approvable")
            if expected_hash is not None and expected_hash != order.content_hash:
                raise ConflictError("Approval does not match the displayed exact order")
            approval = ApprovalRecord(intent_id=order.intent_id, actor=actor, action="approve_order", before_payload={"status": order.state},
                after_payload={"status": "approved", "order_hash": order.content_hash, "exact_order": order.order})
            session.add(approval)
            session.flush()
            session.add(ApprovalLedgerRecord(room_id="market", source="paper_execution", entity_type="exact_paper_order", entity_id=order.order_id,
                action="accept", actor=actor, summary="Human approval of an exact paper limit order", payload={"order_hash": order.content_hash, "order": order.order}))
            order.state = "approved"
            session.add(order)
            intent.status, intent.updated_at = "approved", now_utc()
            session.add(intent)
            self._execution_event(session, order, "approved", {"actor": actor, "order_hash": order.content_hash,"approval_id":approval.approval_id})
        return order

    def claim(self, order_id: str, snapshot: PaperAccountSnapshot) -> tuple[PaperExecutionAttemptRecord, bool]:
        with self.transaction() as session:
            order = require(session, ExactPaperOrderRecord, order_id)
            previous = session.exec(select(PaperExecutionAttemptRecord).where(PaperExecutionAttemptRecord.order_id == order_id)).first()
            if previous:
                return previous, False  # Never POST a claimed attempt again.
            exact, policy = ExactPaperOrder.model_validate(order.order), ExecutionPolicy.model_validate(order.policy)
            if account_key(snapshot) != order.account_key:
                raise ConflictError("Paper provider/account changed after preview")
            account = require(session, PaperExecutionAccountRecord, order.account_key)
            if account.writer_attempt_id:
                raise ConflictError("Another account submission must be reconciled first")
            if account.last_execution_at and snapshot.started_at <= account.last_execution_at:
                raise ConflictError("Account changed after this snapshot; refresh before submission")
            if order.state != "approved" or exact.expires_at <= now_utc():
                raise ConflictError("Exact order is unapproved or expired")
            intent = require(session, TradeIntentRecord, order.intent_id)
            if require(session, RunRecord, intent.run_id).config.get("broker_mode") != "paper":
                raise ConflictError("Paper execution was disabled before submission")
            approval = session.exec(select(ApprovalRecord).where(ApprovalRecord.intent_id == order.intent_id).where(ApprovalRecord.action.in_({"approve_order", "reject_order", "revoke_order", "cancel_order"})).order_by(ApprovalRecord.created_at.desc())).first()
            if not approval or approval.action != "approve_order" or approval.after_payload.get("status") != "approved" or approval.after_payload.get("order_hash") != order.content_hash:
                raise ConflictError("Exact order approval was revoked, changed or missing")
            from tradingagents.scheduling.repository import check_scheduled_dispatch
            check_scheduled_dispatch(session, order)
            reservations, attempts = self._pending(session, order.account_key)
            risk_check(snapshot, exact, policy, reservations, attempts)
            from tradingagents.research.deployment_repository import check_deployment_order
            check_deployment_order(session, order.deployment_id, order.target_id, snapshot, exact, policy)
            attempt = PaperExecutionAttemptRecord(order_id=order_id, account_key=order.account_key, client_order_id=order.intent_id, approval_id=approval.approval_id)
            session.add(attempt)
            session.flush()
            session.add(PaperReservationRecord(attempt_id=attempt.attempt_id, account_key=order.account_key, symbol=exact.symbol, side=exact.side,
                risk_group=exact.risk_group, quantity=str(exact.quantity), price_usd=str(exact.limit_price_usd), fee_usd=str(exact.fee_reserve_usd)))
            account.writer_attempt_id, account.last_execution_at = attempt.attempt_id, now_utc()
            account.snapshot = snapshot.model_dump(mode="json")
            order.state = "dispatching"
            intent = require(session, TradeIntentRecord, order.intent_id)
            intent.status, intent.updated_at = "dispatching", now_utc()
            session.add(account); session.add(order); session.add(intent)
            self._execution_event(session, order, "dispatch_claimed", {"approval_id": approval.approval_id, "snapshot": snapshot.model_dump(mode="json")}, attempt.attempt_id)
        return attempt, True

    def unknown(self, attempt_id: str, reason: str) -> PaperExecutionAttemptRecord:
        with self.transaction() as session:
            attempt = require(session, PaperExecutionAttemptRecord, attempt_id)
            if attempt.state in TERMINAL:
                return attempt
            order = require(session, ExactPaperOrderRecord, attempt.order_id)
            account = require(session, PaperExecutionAccountRecord, attempt.account_key)
            attempt.state, attempt.failure_reason, attempt.updated_at = "unknown", reason[:1000], now_utc()
            order.state = "unknown"
            if account.writer_attempt_id == attempt_id:
                account.writer_attempt_id = None
            account.last_execution_at = now_utc()
            intent = require(session, TradeIntentRecord, order.intent_id)
            intent.status, intent.updated_at = "unknown", now_utc()
            session.add(attempt); session.add(order); session.add(account); session.add(intent)
            self._execution_event(session, order, "submission_unknown", {"reason": reason[:1000], "reservation_retained": True}, attempt_id)
        return attempt

    def observe(self, attempt_id: str, observation: PaperOrderObservation) -> PaperExecutionAttemptRecord:
        with self.transaction() as session:
            attempt = require(session, PaperExecutionAttemptRecord, attempt_id)
            order = require(session, ExactPaperOrderRecord, attempt.order_id)
            exact = ExactPaperOrder.model_validate(order.order)
            if (observation.client_order_id, observation.symbol, observation.side, observation.quantity) != (attempt.client_order_id, exact.symbol, exact.side, exact.quantity):
                raise ConflictError("Broker observation does not match the exact submitted order")
            if attempt.broker_order_id and attempt.broker_order_id != observation.broker_order_id:
                raise ConflictError("Broker order identity changed for the same client order ID")
            previous = PaperOrderObservation.model_validate(attempt.observation) if attempt.observation else None
            if observation.filled_quantity < D(attempt.filled_quantity) or (attempt.state in TERMINAL and observation.status not in TERMINAL and observation.filled_quantity == D(attempt.filled_quantity)):
                self._execution_event(session, order, "stale_observation_ignored", {"observation": observation.model_dump(mode="json")}, attempt_id)
                return attempt
            if previous and (previous.status, previous.filled_quantity, previous.average_fill_price_usd) == (observation.status, observation.filled_quantity, observation.average_fill_price_usd):
                return attempt
            account = require(session, PaperExecutionAccountRecord, attempt.account_key)
            reservation = require(session, PaperReservationRecord, attempt_id)
            attempt.state, attempt.filled_quantity = observation.status, str(observation.filled_quantity)
            attempt.broker_order_id, attempt.observation = observation.broker_order_id, observation.model_dump(mode="json")
            attempt.failure_reason, attempt.updated_at = None, now_utc()
            reservation.quantity = str(D(exact.quantity) - observation.filled_quantity)
            reservation.active = observation.status not in TERMINAL
            order.state = "pending_cancel" if order.state == "pending_cancel" and observation.status not in TERMINAL else observation.status
            if account.writer_attempt_id == attempt_id:
                account.writer_attempt_id = None
            account.last_execution_at = now_utc()
            intent = require(session, TradeIntentRecord, order.intent_id)
            intent.status, intent.updated_at = order.state, now_utc()
            broker_row = session.exec(select(BrokerOrderRecord).where(BrokerOrderRecord.intent_id == order.intent_id).where(BrokerOrderRecord.broker_order_id == observation.broker_order_id)).first()
            if broker_row is None:
                broker_row = BrokerOrderRecord(intent_id=order.intent_id, broker=account.provider_id, environment="paper", status=observation.status, broker_order_id=observation.broker_order_id)
            broker_row.status, broker_row.updated_at = observation.status, now_utc()
            broker_row.payload = {"exact_order": order.order, "observation": observation.model_dump(mode="json"), "attempt_id": attempt_id}
            for record in (attempt, reservation, order, account, intent, broker_row): session.add(record)
            self._execution_event(session, order, "broker_observed", {"observation": observation.model_dump(mode="json")}, attempt_id)
        return attempt

    def request_cancel(self, order_id: str, actor: str, *, session=None) -> PaperExecutionAttemptRecord | None:
        with (self.transaction() if session is None else nullcontext(session)) as session:
            order = require(session, ExactPaperOrderRecord, order_id)
            attempt = session.exec(select(PaperExecutionAttemptRecord).where(PaperExecutionAttemptRecord.order_id == order_id)).first()
            if order.state == "pending_cancel" and attempt:
                return attempt
            session.add(ApprovalRecord(intent_id=order.intent_id, actor=actor, action="cancel_order", after_payload={"status": "revoked", "order_hash": order.content_hash}))
            session.add(ApprovalLedgerRecord(room_id="market", source="paper_execution", entity_type="exact_paper_order", entity_id=order.order_id,
                action="reject", actor=actor, summary="Cancellation request; outstanding reservations await broker confirmation",
                payload={"order_hash": order.content_hash, "submission_attempt_exists": attempt is not None}))
            if attempt and attempt.state not in TERMINAL:
                order.state = "pending_cancel"
                intent = require(session, TradeIntentRecord, order.intent_id)
                intent.status, intent.updated_at = "pending_cancel", now_utc()
                session.add(intent)
                # Keep the last broker state and full remaining reservation
                # until a broker observation acknowledges the cancellation.
                self._execution_event(session, order, "cancel_requested", {"actor": actor, "reservation_retained": True}, attempt.attempt_id)
            elif not attempt:
                order.state = "canceled"
                intent = require(session, TradeIntentRecord, order.intent_id)
                intent.status, intent.updated_at = "canceled", now_utc()
                session.add(intent)
                self._execution_event(session, order, "preview_canceled", {"actor": actor})
            session.add(order)
        return attempt

    @staticmethod
    def _pending(session, key):
        reservations = list(session.exec(select(PaperReservationRecord).where(PaperReservationRecord.account_key == key).where(PaperReservationRecord.active == True)))
        attempts = {r.attempt_id: require(session, PaperExecutionAttemptRecord, r.attempt_id) for r in reservations}
        return reservations, attempts

    @staticmethod
    def _execution_event(session, order, kind, payload, attempt_id=None):
        session.add(PaperExecutionEventRecord(order_id=order.order_id, attempt_id=attempt_id, kind=kind, payload=payload))


def install_execution_guards(engine):
    with engine.begin() as connection:
        for action in ("UPDATE","DELETE"):
            connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS paper_exact_approval_no_{action.lower()} BEFORE {action} ON ui_approvals WHEN EXISTS (SELECT 1 FROM paper_exact_orders WHERE intent_id=OLD.intent_id) BEGIN SELECT RAISE(ABORT, 'exact paper approval history is immutable'); END"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS paper_exact_target_once ON paper_exact_orders(target_id) WHERE target_id IS NOT NULL"))
        for action in ("UPDATE", "DELETE"):
            connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS paper_execution_events_no_{action.lower()} BEFORE {action} ON paper_execution_events BEGIN SELECT RAISE(ABORT, 'paper execution history is immutable'); END"))
        for table, fields in {
            "paper_exact_orders": ("intent_id", "account_key", "deployment_id", "target_id", "content_hash", "order", "policy", "preview_snapshot", "created_at"),
            "paper_execution_attempts": ("order_id", "account_key", "client_order_id", "approval_id", "created_at"),
        }.items():
            condition = " OR ".join(f'OLD."{name}" IS NOT NEW."{name}"' for name in fields)
            connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS {table}_pin BEFORE UPDATE ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT, 'exact paper order pin is immutable'); END"))
            connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'paper attempt history is immutable'); END"))
