from datetime import timedelta
from pathlib import Path

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig, RunEvent
from tradingagents.ui.repository import UiRepository


def _repo(tmp_path: Path) -> UiRepository:
    db_url = f"sqlite:///{tmp_path / 'ui.db'}"
    engine, session_factory = create_session_factory(db_url)
    init_db(engine)
    return UiRepository(session_factory)


def test_create_run_and_list_runs(tmp_path):
    repo = _repo(tmp_path)
    config = RunConfig(ticker="NVDA", trade_date="2026-04-30")

    run = repo.create_run(config)
    runs = repo.list_runs()

    assert run.ticker == "NVDA"
    assert run.status == "queued"
    assert len(runs) == 1
    assert runs[0].run_id == run.run_id


def test_append_events_preserves_sequence(tmp_path):
    repo = _repo(tmp_path)
    run = repo.create_run(RunConfig(ticker="MSFT", trade_date="2026-04-30"))

    first = repo.append_event(
        RunEvent(run_id=run.run_id, sequence=1, type="run.started", message="Started")
    )
    second = repo.append_event(
        RunEvent(
            run_id=run.run_id,
            sequence=2,
            type="agent.started",
            node="Market Analyst",
            message="Market Analyst started",
        )
    )

    events = repo.list_events(run.run_id)

    assert [e.sequence for e in events] == [first.sequence, second.sequence]
    assert events[1].node == "Market Analyst"


def test_store_decision_updates_run_summary(tmp_path):
    repo = _repo(tmp_path)
    run = repo.create_run(RunConfig(ticker="AAPL", trade_date="2026-04-30"))

    decision = repo.store_decision(
        run_id=run.run_id,
        rating="Overweight",
        action="Buy",
        thesis="Momentum and fundamentals support a gradual build.",
        risk_notes="Size conservatively before earnings.",
    )
    summary = repo.get_run(run.run_id)

    assert decision.rating == "Overweight"
    assert summary.final_rating == "Overweight"
    assert summary.final_action == "Buy"


def test_persisted_run_timestamps_remain_utc_aware(tmp_path):
    repo = _repo(tmp_path)
    run = repo.create_run(RunConfig(ticker="TSLA", trade_date="2026-04-30"))

    reread = repo.get_run(run.run_id)

    assert reread.created_at.tzinfo is not None
    assert reread.created_at.utcoffset() == timedelta(0)
    assert reread.updated_at.tzinfo is not None
    assert reread.updated_at.utcoffset() == timedelta(0)


def test_latest_approval_status_controls_has_approval(tmp_path):
    repo = _repo(tmp_path)
    run = repo.create_run(RunConfig(ticker="AMD", trade_date="2026-04-30"))
    intent = repo.create_trade_intent(
        run_id=run.run_id,
        symbol="AMD",
        side="buy",
        notional=5000,
    )

    approval = repo.record_approval(
        intent_id=intent.intent_id,
        actor="mcurtis",
        action="approve_order",
        before_payload={"status": "previewed"},
        after_payload={"status": "approved"},
    )

    assert approval.intent_id == intent.intent_id
    assert repo.has_approval(intent.intent_id)

    repo.record_approval(
        intent_id=intent.intent_id,
        actor="mcurtis",
        action="approve_order",
        before_payload={"status": "approved"},
        after_payload={"status": "rejected"},
    )

    assert not repo.has_approval(intent.intent_id)


def test_later_rejection_action_clears_has_approval(tmp_path):
    repo = _repo(tmp_path)
    run = repo.create_run(RunConfig(ticker="AMD", trade_date="2026-04-30"))
    intent = repo.create_trade_intent(
        run_id=run.run_id,
        symbol="AMD",
        side="buy",
        notional=5000,
    )

    repo.record_approval(
        intent_id=intent.intent_id,
        actor="mcurtis",
        action="approve_order",
        before_payload={"status": "previewed"},
        after_payload={"status": "approved"},
    )
    repo.record_approval(
        intent_id=intent.intent_id,
        actor="mcurtis",
        action="reject_order",
        before_payload={"status": "approved"},
        after_payload={"status": "rejected"},
    )

    assert repo.has_approval(intent.intent_id) is False


def test_store_broker_order_updates_intent_status_with_plan_names(tmp_path):
    repo = _repo(tmp_path)
    run = repo.create_run(RunConfig(ticker="NVDA", trade_date="2026-04-30"))
    intent = repo.create_trade_intent(
        run_id=run.run_id,
        symbol="NVDA",
        side="buy",
        notional=10000,
    )

    order = repo.store_broker_order(
        intent_id=intent.intent_id,
        broker="alpaca",
        environment="paper",
        status="submitted",
        broker_order_id="broker-123",
    )
    reread = repo.get_trade_intent(intent.intent_id)

    assert intent.status == "previewed"
    assert order.intent_id == intent.intent_id
    assert order.broker_order_id == "broker-123"
    assert reread.status == "submitted"
