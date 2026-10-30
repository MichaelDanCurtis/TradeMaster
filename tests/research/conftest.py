import pytest

from tradingagents.research.contracts import (
    ExperimentInput, FreezeVersion, ResearchPlanInput, SnapshotManifest, StrategyDraft, StrategySpec,
)
from tradingagents.research.repository import ResearchRepository
from tradingagents.ui.db import create_session_factory, init_db


def spec_payload():
    return {
        "universe": [{"instrument_id": "etf_a", "symbol": "AAA", "risk_group": "equity"}],
        "rules": {"kind": "diversified_trend", "lookbacks_sessions": [2, 3, 4], "volatility_sessions": 3},
        "risk": {"max_position_fraction": "0.5", "max_group_fraction": "0.6", "cash_reserve_fraction": "0.1", "max_turnover_fraction": "1", "max_drawdown_fraction": "0.2"},
    }


def plan_payload(strategy_id, version_id):
    return {
        "strategy_id": strategy_id, "family_id": "trend_family", "version_ids": [version_id],
        "split": {"train_start": "2020-01-01", "train_end": "2020-03-31", "validation_start": "2020-04-01", "validation_end": "2020-06-30", "holdout_start": "2020-07-01", "holdout_end": "2020-09-30"},
        "initial_capital_usd": "10000", "max_trials": 30, "compute_budget_usd": "10",
        "scenarios": [
            {"name": "base", "slippage_bps": "5", "commission_usd": "1"},
            {"name": "double_cost", "slippage_bps": "10", "commission_usd": "2"},
            {"name": "delayed", "slippage_bps": "5", "commission_usd": "1", "execution_delay_sessions": 1},
        ],
        "criteria": {"min_observations": 30, "min_net_excess_return_fraction": "0.01", "max_drawdown_fraction": "0.2", "rationale": "Predeclared research criterion, not a return promise"},
    }


def snapshot_payload():
    return {
        "provider": "fixture", "evidence_kind": "fixture", "provenance": "Synthetic testing only",
        "entitlement": "repository fixture", "calendar": "test_sessions", "timezone": "America/New_York",
        "coverage_start": "2019-01-01", "coverage_end": "2020-12-31", "instrument_ids": ["etf_a"],
        "artifacts": {"dataset": "a" * 64}, "availability": "synthetic",
    }


@pytest.fixture
def repository(tmp_path):
    engine, sessions = create_session_factory(f"sqlite:///{tmp_path / 'research.db'}")
    init_db(engine)
    yield ResearchRepository(sessions)
    engine.dispose()


@pytest.fixture
def setup_research(repository):
    strategy = repository.create_strategy(StrategyDraft(name="Trend", hypothesis="Persistent price moves", rationale="Test a deterministic baseline"))
    version = repository.freeze_version(strategy.strategy_id, FreezeVersion(spec=StrategySpec.model_validate(spec_payload())))
    plan = repository.freeze_plan(ResearchPlanInput.model_validate(plan_payload(strategy.strategy_id, version.version_id)))
    snapshot = repository.register_snapshot(SnapshotManifest.model_validate(snapshot_payload()))
    request = ExperimentInput(plan_id=plan.plan_id, snapshot_id=snapshot.snapshot_id, idempotency_key="first_run")
    return strategy, version, plan, snapshot, request
