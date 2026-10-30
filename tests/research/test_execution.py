from datetime import timedelta
from decimal import Decimal as D
from threading import Barrier, Thread

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from tradingagents.research.execution_contracts import AccountPosition
from tradingagents.research.execution_models import ExactPaperOrderRecord, PaperReservationRecord, PaperExecutionAttemptRecord
from tradingagents.research.execution_repository import PaperExecutionRepository
from tradingagents.research.repository import ConflictError
from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.brokers.service import BrokerService
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig
from tradingagents.ui.models import BrokerOrderRecord, TradeIntentRecord
from tradingagents.ui.repository import UiRepository


@pytest.fixture
def execution(tmp_path):
    engine, sessions = create_session_factory(f"sqlite:///{tmp_path/'paper.db'}")
    init_db(engine)
    repo = UiRepository(sessions)
    run = repo.create_run(RunConfig(ticker="AAA", trade_date="2026-04-30", broker_mode="paper"))
    broker = FakePaperBroker(cash_usd="1000")
    return BrokerService(repo, broker), repo, broker, run.run_id, PaperExecutionRepository(sessions)


def approved(execution, *, symbol="AAA", amount=600, side="buy"):
    service, _, _, run_id, _ = execution
    preview = service.preview_order(run_id=run_id, symbol=symbol, side=side, notional=amount)
    service.approve_order(preview.intent_id, "operator")
    return preview


def test_exact_quantity_limit_and_hash_are_frozen_before_approval(execution):
    service, _, _, run_id, boundary = execution
    preview = service.preview_order(run_id=run_id, symbol="AAA", side="buy", notional=650)
    assert preview.estimated_quantity == 6
    assert preview.exact_order["quantity"] == 6 and preview.exact_order["limit_price_usd"] == "100.00"
    record = boundary.for_intent(preview.intent_id)
    with pytest.raises(ConflictError, match="displayed exact"):
        boundary.approve(record.order_id, "operator", "0"*64)
    with boundary.sessions() as session:
        with pytest.raises(IntegrityError, match="immutable"):
            session.execute(text('UPDATE paper_exact_orders SET "order" = :payload WHERE order_id = :id'), {"payload": '{}', "id": record.order_id})
            session.commit()


def test_stale_snapshot_and_post_preview_capital_change_fail_before_http(execution, monkeypatch):
    service, _, broker, _, _ = execution
    preview = approved(execution)
    original = broker.paper_snapshot
    stale = original()
    stale.started_at -= timedelta(minutes=1)
    monkeypatch.setattr(broker, "paper_snapshot", lambda: stale)
    with pytest.raises(ConflictError, match="stale"):
        service.submit_approved_order(preview.intent_id)
    monkeypatch.setattr(broker, "paper_snapshot", original)
    broker.cash_usd = D(400)
    with pytest.raises(ConflictError, match="Cash|Drawdown"):
        service.submit_approved_order(preview.intent_id)
    assert broker.economic_orders == 0


def test_revoked_approval_cannot_claim_a_new_submission(execution):
    service, repo, broker, _, _ = execution
    preview = approved(execution)
    repo.record_approval(preview.intent_id, "operator", "revoke_order", {}, {"status": "revoked"})
    with pytest.raises(PermissionError, match="requires approval"):
        service.submit_approved_order(preview.intent_id)
    assert broker.economic_orders == 0


def test_account_writer_and_reservations_serialize_competing_orders(execution):
    service, _, broker, _, boundary = execution
    first, second = approved(execution), approved(execution, symbol="BBB")
    barrier, results = Barrier(2), []
    snapshot = broker.paper_snapshot()
    def claim(preview):
        barrier.wait()
        try: results.append(boundary.claim(boundary.for_intent(preview.intent_id).order_id, snapshot))
        except ConflictError as exc: results.append(str(exc))
    threads = [Thread(target=claim, args=(preview,)) for preview in (first, second)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    claimed = [r for r in results if isinstance(r, tuple)]
    assert len(claimed) == 1 and claimed[0][1]
    attempt = claimed[0][0]
    # Unknown outcomes keep the reservation even after releasing the writer.
    boundary.unknown(attempt.attempt_id, "simulated interrupted caller")
    loser = next(p for p in (first, second) if p.intent_id != attempt.client_order_id)
    with pytest.raises(ConflictError, match="unresolved"):
        service.submit_approved_order(loser.intent_id)
    assert broker.economic_orders == 0


def test_partial_fill_and_unacknowledged_cancellation_keep_remaining_commitment(execution, monkeypatch):
    service, _, broker, _, boundary = execution
    first, second = approved(execution), approved(execution, symbol="BBB")
    service.submit_approved_order(first.intent_id)
    broker.fill(first.intent_id, 3)
    service.reconcile_order(first.intent_id)
    attempt = boundary.attempt_for_order(boundary.for_intent(first.intent_id).order_id)
    with boundary.sessions() as session:
        reserve = session.get(PaperReservationRecord, attempt.attempt_id)
        assert reserve.active and D(reserve.quantity) == 3
        assert len(list(session.exec(select(BrokerOrderRecord)))) == 1
    monkeypatch.setattr(broker, "cancel_exact_order", lambda _: None)
    assert service.cancel_order(first.intent_id, "operator") == "pending_cancel"
    with pytest.raises(ConflictError, match="Cash|exposure"):
        service.submit_approved_order(second.intent_id)
    assert broker.economic_orders == 1
    broker.observations[first.intent_id] = broker.observations[first.intent_id].model_copy(update={"status": "canceled"})
    service.reconcile_order(first.intent_id)
    with boundary.sessions() as session:
        assert not session.get(PaperReservationRecord, attempt.attempt_id).active
    service.submit_approved_order(second.intent_id)
    assert broker.economic_orders == 2


def test_lost_acknowledgement_is_reconciled_without_second_post(execution, monkeypatch):
    service, _, broker, _, boundary = execution
    preview = approved(execution)
    original = broker.submit_exact_order
    def lost(client_id, order):
        original(client_id, order)
        raise TimeoutError("response lost after acceptance")
    monkeypatch.setattr(broker, "submit_exact_order", lost)
    assert service.submit_approved_order(preview.intent_id).status == "unknown"
    result = service.submit_approved_order(preview.intent_id)
    assert result.status == "accepted" and broker.economic_orders == 1
    assert [e.kind for e in boundary.history(boundary.for_intent(preview.intent_id).order_id)] == ["previewed", "approved", "dispatch_claimed", "submission_unknown", "broker_observed"]


def test_supervisor_crash_after_acceptance_and_repository_restart_never_posts_again(execution, monkeypatch):
    service, repo, broker, _, boundary = execution
    preview = approved(execution)
    original = broker.submit_exact_order
    def crash(client_id, order):
        original(client_id, order)
        raise SystemExit("simulated supervisor death")
    monkeypatch.setattr(broker, "submit_exact_order", crash)
    with pytest.raises(SystemExit): service.submit_approved_order(preview.intent_id)
    engine, sessions = create_session_factory(str(repo._session_factory.kw["bind"].url))
    init_db(engine)
    recovered = BrokerService(UiRepository(sessions), broker)
    assert recovered.submit_approved_order(preview.intent_id).status == "accepted"
    assert broker.economic_orders == 1
    with boundary.sessions() as session:
        assert len(list(session.exec(select(PaperExecutionAttemptRecord)))) == 1
    engine.dispose()


def test_absent_unknown_order_stays_unknown_and_is_never_retried(execution, monkeypatch):
    service, _, broker, _, _ = execution
    preview = approved(execution)
    calls = []
    def unavailable(*args):
        calls.append(args)
        raise ConnectionError("unknown acceptance")
    monkeypatch.setattr(broker, "submit_exact_order", unavailable)
    for _ in range(3): assert service.submit_approved_order(preview.intent_id).status == "unknown"
    assert len(calls) == 1 and broker.economic_orders == 0


def test_current_external_holdings_are_counted_and_reductions_do_not_short(execution):
    service, _, broker, _, _ = execution
    preview = approved(execution)
    broker.positions["BBB"] = AccountPosition(symbol="BBB", quantity=8, market_value_usd=800, cost_basis_usd=800)
    broker.cash_usd = D(200)
    with pytest.raises(ConflictError, match="Cash"):
        service.submit_approved_order(preview.intent_id)
    reduction = approved(execution, symbol="BBB", amount=300, side="sell")
    assert service.submit_approved_order(reduction.intent_id).status == "accepted"
    with pytest.raises(ConflictError, match="unreserved current holdings"):
        approved(execution, symbol="BBB", amount=600, side="sell")


def test_stale_late_broker_update_cannot_decrease_fills_or_reopen_terminal_order(execution):
    service, _, broker, _, boundary = execution
    preview = approved(execution)
    service.submit_approved_order(preview.intent_id)
    initial = broker.observations[preview.intent_id]
    broker.fill(preview.intent_id, 6)
    service.reconcile_order(preview.intent_id)
    attempt = boundary.attempt_for_order(boundary.for_intent(preview.intent_id).order_id)
    stale = boundary.observe(attempt.attempt_id, initial)
    assert stale.state == "filled" and D(stale.filled_quantity) == 6


def test_changed_provider_account_cannot_lookup_or_cancel_an_approved_order(execution, monkeypatch):
    service, _, broker, _, _ = execution
    preview = approved(execution)
    service.submit_approved_order(preview.intent_id)
    other = broker.paper_snapshot().model_copy(update={"account_id": "other-account"})
    monkeypatch.setattr(broker, "paper_snapshot", lambda: other)
    for operation in (lambda: service.reconcile_order(preview.intent_id), lambda: service.cancel_order(preview.intent_id, "operator")):
        with pytest.raises(ConflictError, match="approved account"):
            operation()


def test_legacy_notional_only_intent_cannot_use_the_new_submission_boundary(execution):
    service, repo, broker, run_id, _ = execution
    intent = repo.create_trade_intent(run_id, "AAA", "buy", 100)
    repo.record_approval(intent.intent_id, "operator", "approve_order", {}, {"status": "approved"})
    with pytest.raises(PermissionError, match="fresh exact"):
        service.submit_approved_order(intent.intent_id)
    assert broker.economic_orders == 0


def test_missing_drawdown_allows_only_funded_reductions(execution, monkeypatch):
    service, _, broker, run_id, _ = execution
    broker.positions["AAA"] = AccountPosition(symbol="AAA", quantity=5, market_value_usd=500, cost_basis_usd=500)
    original = broker.paper_snapshot
    monkeypatch.setattr(broker, "paper_snapshot", lambda: original().model_copy(update={"drawdown_fraction": None}))
    with pytest.raises(ConflictError, match="drawdown is unavailable"):
        service.preview_order(run_id, "AAA", "buy", 100)
    reduction = service.preview_order(run_id, "AAA", "sell", 200)
    service.approve_order(reduction.intent_id, "operator", reduction.order_hash)
    assert service.submit_approved_order(reduction.intent_id).status == "accepted"


def test_partial_fill_during_pending_cancel_retains_cancellation_state(execution, monkeypatch):
    service, _, broker, _, boundary = execution
    order = approved(execution)
    service.submit_approved_order(order.intent_id)
    monkeypatch.setattr(broker, "cancel_exact_order", lambda _: None)
    assert service.cancel_order(order.intent_id, "operator") == "pending_cancel"
    broker.fill(order.intent_id, 2)
    assert service.reconcile_order(order.intent_id).status == "partially_filled"
    assert boundary.for_intent(order.intent_id).state == "pending_cancel"
    assert service.execution_history(order.intent_id)["attempt"].observation["filled_quantity"] == "2"
