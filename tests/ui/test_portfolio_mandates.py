from pathlib import Path

import pytest

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.repository import UiRepository


def _repo(tmp_path: Path) -> UiRepository:
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    return UiRepository(session_factory)


def test_human_managed_webull_mandate_is_approval_first(tmp_path: Path):
    repo = _repo(tmp_path)

    mandate = repo.create_portfolio_mandate(
        name="Webull human-managed strategy",
        control_mode="human-managed",
        account_ref="webull:manual",
        funding_limit=25000,
        max_position_percent=20,
        max_drawdown_percent=8,
        daily_turnover_limit_percent=25,
        paper_mode_required=False,
        kill_switch_enabled=True,
        payload={"surface": "webull"},
    )

    assert mandate.control_mode == "human-managed"
    assert mandate.account_ref == "webull:manual"
    assert mandate.status == "draft"
    assert mandate.payload == {"surface": "webull"}


def test_ai_managed_high_risk_mandate_requires_paper_and_kill_switch(tmp_path: Path):
    repo = _repo(tmp_path)

    with pytest.raises(ValueError, match="paper mode"):
        repo.create_portfolio_mandate(
            name="AI high-risk harness",
            control_mode="ai-managed-high-risk",
            account_ref="alpaca:high-risk",
            funding_limit=5000,
            max_position_percent=10,
            max_drawdown_percent=5,
            daily_turnover_limit_percent=30,
            paper_mode_required=False,
            kill_switch_enabled=True,
        )

    with pytest.raises(ValueError, match="kill switch"):
        repo.create_portfolio_mandate(
            name="AI high-risk harness",
            control_mode="ai-managed-high-risk",
            account_ref="alpaca:high-risk",
            funding_limit=5000,
            max_position_percent=10,
            max_drawdown_percent=5,
            daily_turnover_limit_percent=30,
            paper_mode_required=True,
            kill_switch_enabled=False,
        )


def test_ai_managed_high_risk_mandate_records_funding_boundary(tmp_path: Path):
    repo = _repo(tmp_path)

    mandate = repo.create_portfolio_mandate(
        name="AI high-risk harness",
        control_mode="ai-managed-high-risk",
        account_ref="alpaca:paper:high-risk",
        funding_limit=5000,
        max_position_percent=10,
        max_drawdown_percent=5,
        daily_turnover_limit_percent=30,
        paper_mode_required=True,
        kill_switch_enabled=True,
        status="paper-testing",
    )
    mandates = repo.list_portfolio_mandates(control_mode="ai-managed-high-risk")

    assert mandate.status == "paper-testing"
    assert mandate.funding_limit == 5000
    assert mandate.paper_mode_required is True
    assert mandate.kill_switch_enabled is True
    assert mandates[0].mandate_id == mandate.mandate_id
