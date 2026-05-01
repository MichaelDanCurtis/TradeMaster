from pathlib import Path

import pytest
from sqlmodel import select

from tradingagents.ui.brokers.base import BrokerOrder, OrderSide
from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.brokers.service import BrokerService
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.events import RunConfig
from tradingagents.ui.models import TradeIntentRecord
from tradingagents.ui.repository import UiRepository


class CountingFakePaperBroker(FakePaperBroker):
    def __init__(self) -> None:
        self.submit_count = 0

    def submit_order(
        self, intent_id: str, symbol: str, side: OrderSide, notional: float
    ) -> BrokerOrder:
        self.submit_count += 1
        return super().submit_order(intent_id, symbol, side, notional)


def _service(tmp_path: Path) -> tuple[BrokerService, UiRepository, str]:
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)
    run = repo.create_run(
        RunConfig(ticker="NVDA", trade_date="2026-04-30", broker_mode="paper")
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
    assert order.status == "submitted"
    assert order.broker_order_id.startswith("fake_order_")


def test_duplicate_submit_is_rejected_before_broker_call(tmp_path):
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
    service.submit_approved_order(preview.intent_id)

    with pytest.raises(ValueError, match="already submitted|not previewed"):
        service.submit_approved_order(preview.intent_id)
    assert broker.submit_count == 1


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
