from pathlib import Path

import pytest
from sqlmodel import select

from tradingagents.ui.brokers.base import BrokerOrder, OrderSide
from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.brokers.service import BrokerService
from tradingagents.ui.constraints import (
    ConstraintContext,
    PortfolioConstraintPolicy,
    SymbolicConstraintEngine,
)
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig
from tradingagents.ui.models import TradeIntentRecord
from tradingagents.ui.repository import UiRepository


class CountingFakePaperBroker(FakePaperBroker):
    def __init__(self) -> None:
        super().__init__()
        self.submit_count = 0

    def submit_exact_order(self, client_order_id, order):
        self.submit_count += 1
        return super().submit_exact_order(client_order_id, order)


def _service(tmp_path: Path) -> tuple[BrokerService, UiRepository, str]:
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    run = repo.create_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", broker_mode="paper")
    )
    return BrokerService(repo, FakePaperBroker()), repo, run.run_id


def _service_with_broker_mode(
    tmp_path: Path, broker_mode: str
) -> tuple[BrokerService, UiRepository, str]:
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    run = repo.create_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", broker_mode=broker_mode)
    )
    return BrokerService(repo, FakePaperBroker()), repo, run.run_id


def test_create_trade_preview_records_intent(tmp_path):
    service, repo, run_id = _service(tmp_path)

    preview = service.preview_order(
        run_id=run_id, symbol="NVDA", side="buy", notional=1000
    )

    intent = repo.get_trade_intent(preview.intent_id)
    assert preview.environment == "paper"
    assert intent.status == "previewed"


def test_disabled_run_cannot_preview_trade(tmp_path):
    service, _, run_id = _service_with_broker_mode(tmp_path, "disabled")

    with pytest.raises(PermissionError, match="broker_mode=paper"):
        service.preview_order(
            run_id=run_id, symbol="NVDA", side="buy", notional=1000
        )


def test_disabled_run_cannot_submit_existing_intent(tmp_path):
    service, repo, run_id = _service_with_broker_mode(tmp_path, "disabled")
    intent = repo.create_trade_intent(
        run_id=run_id, symbol="NVDA", side="buy", notional=1000
    )

    with pytest.raises(PermissionError, match="broker_mode=paper"):
        service.approve_order(intent.intent_id, actor="local-user")

    repo.record_approval(
        intent_id=intent.intent_id,
        actor="test",
        action="approve_order",
        before_payload={"status": intent.status},
        after_payload={"status": "approved"},
    )
    with pytest.raises(PermissionError, match="broker_mode=paper"):
        service.submit_approved_order(intent.intent_id)


def test_submit_order_requires_approval(tmp_path):
    service, _, run_id = _service(tmp_path)
    preview = service.preview_order(
        run_id=run_id, symbol="NVDA", side="buy", notional=1000
    )

    with pytest.raises(PermissionError, match="requires approval"):
        service.submit_approved_order(preview.intent_id)


def test_approved_order_submits_to_fake_broker(tmp_path):
    service, repo, run_id = _service(tmp_path)
    preview = service.preview_order(
        run_id=run_id, symbol="NVDA", side="buy", notional=1000
    )

    service.approve_order(preview.intent_id, actor="local-user")
    order = service.submit_approved_order(preview.intent_id)

    assert order.environment == "paper"
    assert order.status == "accepted"
    assert order.broker_order_id.startswith("fake_order_")


def test_duplicate_submit_reconciles_without_another_economic_order(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    broker = CountingFakePaperBroker()
    run = repo.create_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", broker_mode="paper")
    )
    service = BrokerService(repo, broker)
    preview = service.preview_order(
        run_id=run.run_id, symbol="NVDA", side="buy", notional=1000
    )

    service.approve_order(preview.intent_id, actor="local-user")
    first = service.submit_approved_order(preview.intent_id)
    repeated = service.submit_approved_order(preview.intent_id)
    assert repeated.broker_order_id == first.broker_order_id
    assert broker.submit_count == 1
    assert broker.economic_orders == 1


def test_preview_order_rejects_invalid_side_before_creating_intent(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    run = repo.create_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", broker_mode="paper")
    )
    service = BrokerService(repo, FakePaperBroker())

    with pytest.raises(ValueError, match="side must be buy or sell"):
        service.preview_order(
            run_id=run.run_id, symbol="NVDA", side="hold", notional=1000
        )

    with session_factory() as session:
        intents = session.exec(select(TradeIntentRecord)).all()
    assert intents == []


def test_preview_order_applies_symbolic_constraint_gate_before_creating_intent(tmp_path):
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    run = repo.create_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", broker_mode="paper")
    )
    service = BrokerService(
        repo,
        FakePaperBroker(),
        constraint_engine=SymbolicConstraintEngine(),
        constraint_policy=PortfolioConstraintPolicy(
            max_position_percent=5,
            max_sector_percent=100,
            max_daily_turnover_percent=100,
            max_drawdown_percent=100,
            paper_mode_required=True,
        ),
        constraint_context_provider=lambda run_id, symbol: ConstraintContext(
            account_equity=100_000,
            current_position_notional=0,
            sector_exposure_notional=0,
            daily_turnover_notional=0,
            current_drawdown_percent=0,
        ),
    )

    with pytest.raises(ValueError, match="position concentration"):
        service.preview_order(
            run_id=run.run_id,
            symbol="NVDA",
            side="buy",
            notional=10_000,
        )

    with session_factory() as session:
        intents = session.exec(select(TradeIntentRecord)).all()
    assert intents == []


def test_manual_ticket_needs_no_research_run_and_does_not_replace_latest_verdict(tmp_path):
    service, repo, run_id = _service(tmp_path)
    before = repo.list_runs()
    preview = service.preview_order(run_id=None, symbol="NVDA", side="buy", notional=1000)
    intent = repo.get_trade_intent(preview.intent_id)
    context = repo.get_run_config(intent.run_id)
    assert context["purpose"] == "manual_order" and context["analysts"] == []
    assert context["broker_mode"] == "paper"
    assert repo.list_runs() == before
    assert all(row.run_id != intent.run_id for row, _ in repo.latest_completed_runs_by_symbol())
    assert repo.list_events(intent.run_id) == []
    service.approve_order(preview.intent_id, actor="fixture-reviewer", expected_order_hash=preview.order_hash)
    result = service.submit_approved_order(preview.intent_id)
    assert result.status == "accepted"
