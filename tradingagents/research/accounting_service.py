"""Reconciled risk observations; this layer never submits a new broker order."""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import or_
from sqlmodel import select

from tradingagents.research.accounting_contracts import AccountingReconciliation
from tradingagents.research.accounting_repository import PaperAccountingRepository
from tradingagents.research.execution_contracts import PaperAccountIdentity, TERMINAL
from tradingagents.research.execution_models import ExactPaperOrderRecord, PaperExecutionAttemptRecord
from tradingagents.research.execution_repository import PaperExecutionRepository, account_key
from tradingagents.research.execution_service import PaperExecutionService
from tradingagents.research.repository import ConflictError


class ReconciledPaperBroker:
    def __init__(self, broker, accounting: PaperAccountingRepository):
        self.raw, self.accounting = broker, accounting
        self.broker_name, self.environment = broker.broker_name, broker.environment

    def paper_identity(self):
        if callable(getattr(self.raw, "paper_identity", None)): return self.raw.paper_identity()
        snapshot = self.raw.paper_snapshot()
        return PaperAccountIdentity(provider_id=snapshot.provider_id, account_id=snapshot.account_id)

    def paper_snapshot(self):
        snapshot = self.raw.paper_snapshot()
        baseline = self.accounting.baseline(account_key(snapshot))
        if baseline is None: return snapshot
        report = reconcile_snapshot(self.raw, self.accounting, snapshot).report
        drawdown = report.get("drawdown_fraction") if report["reconciled"] else None
        limitations = [line for line in snapshot.limitations if line != "Reconciled drawdown history unavailable; new entries are blocked"]
        limitations.extend(report["limitations"])
        if drawdown is None: limitations.append("Persisted account reconciliation or flow-adjusted drawdown is unavailable; new entries are blocked")
        return snapshot.model_copy(update={"drawdown_fraction":Decimal(drawdown) if drawdown is not None else None, "limitations":limitations})

    def execution_calendar(self, start, end): return self.raw.execution_calendar(start, end)

    def estimate_price(self, symbol): return self.raw.estimate_price(symbol)
    def submit_exact_order(self, client_order_id, order): return self.raw.submit_exact_order(client_order_id, order)
    def find_order(self, client_order_id): return self.raw.find_order(client_order_id)
    def cancel_exact_order(self, client_order_id): return self.raw.cancel_exact_order(client_order_id)
    def order_family(self, broker_order_id): return self.raw.order_family(broker_order_id)


def reconcile_snapshot(broker, accounting, snapshot):
    baseline = accounting.baseline(account_key(snapshot))
    if baseline is None: raise ConflictError("Review an account baseline before recording performance")
    if not callable(getattr(broker, "account_activities", None)):
        raise PermissionError("Broker has no verified account activity capability")
    from tradingagents.research.execution_contracts import PaperAccountSnapshot
    opening = PaperAccountSnapshot.model_validate(baseline.snapshot)
    latest_at = accounting.latest_observed_at(account_key(snapshot))
    # Overlap catches delayed postings and revisions; normalized source IDs
    # deduplicate prior receipts. Continuous coverage is checked transactionally.
    start = max(opening.observed_at, latest_at-timedelta(days=7)) if latest_at else opening.observed_at
    correction_start = accounting.correction_coverage_start(account_key(snapshot))
    if correction_start is not None: start = max(opening.observed_at,min(start,correction_start))
    batch = broker.account_activities(start, snapshot.observed_at)
    with accounting.sessions() as session:
        parents = session.exec(select(PaperExecutionAttemptRecord).join(ExactPaperOrderRecord,
            PaperExecutionAttemptRecord.order_id == ExactPaperOrderRecord.order_id)
            .where(PaperExecutionAttemptRecord.account_key == account_key(snapshot))
            .where(PaperExecutionAttemptRecord.broker_order_id.is_not(None))
            .where(or_(ExactPaperOrderRecord.order["stop_loss_usd"].as_string().is_not(None),
                       ExactPaperOrderRecord.order["take_profit_usd"].as_string().is_not(None)))
            .order_by(PaperExecutionAttemptRecord.attempt_id).limit(101)).all()
    if len(parents) > 100:
        raise ConflictError("Protective order history exceeds this bounded observation; coverage requires review")
    families = []
    if parents:
        if not callable(getattr(broker, "order_family", None)):
            raise PermissionError("Broker has no verified protective-order lineage capability")
        for parent in parents:
            families.append(broker.order_family(parent.broker_order_id))
        identity = broker.paper_identity() if callable(getattr(broker,"paper_identity",None)) else broker.paper_snapshot()
        if account_key(identity) != account_key(snapshot):
            raise ConflictError("Broker identity changed during protective-order observation")
    return accounting.reconcile(AccountingReconciliation(snapshot=snapshot, batch=batch, order_families=families))


def reconcile_paper_account(broker, accounting, expected_account_key):
    identity = broker.paper_identity() if callable(getattr(broker,"paper_identity",None)) else broker.paper_snapshot()
    if account_key(identity) != expected_account_key: raise ConflictError("Configured broker differs from the reviewed account")
    boundary = PaperExecutionRepository(accounting.sessions)
    service = PaperExecutionService(boundary, broker)
    with accounting.sessions() as session:
        attempts = list(session.exec(select(PaperExecutionAttemptRecord).where(PaperExecutionAttemptRecord.account_key == expected_account_key).where(PaperExecutionAttemptRecord.state.notin_(TERMINAL)).limit(101)))
        if len(attempts)>100: raise ConflictError("Too many outstanding orders for one bounded account reconciliation")
        orders = [session.get(ExactPaperOrderRecord, attempt.order_id) for attempt in attempts]
    # Only GET-by-client-ID is used. Unknown or absent acknowledgements cannot
    # trigger a POST while starting/reconnecting the account observer.
    for order in orders: service.reconcile(order)
    snapshot = broker.paper_snapshot()
    if account_key(snapshot) != expected_account_key: raise ConflictError("Broker identity changed during account reconciliation")
    return reconcile_snapshot(broker, accounting, snapshot)
