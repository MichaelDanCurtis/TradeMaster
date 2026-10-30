from datetime import date, timedelta
from decimal import Decimal as D
import os

import pytest

from tradingagents.research.contracts import EquityReference, ExperimentInput, ResearchPlanInput, content_hash
from tradingagents.research.engines.replay import LocalReplayEngine
from tradingagents.research.engines.lean import LeanEngine
from tradingagents.research.evaluation.comparison import evaluate, equity_reference_request
from tradingagents.research.repository import ConflictError
from tests.research.test_replay import request_fixture
from tests.research.test_worker import queue_fixture


def reference(request, fraction=".5"):
    return EquityReference(instrument=request.spec.universe[0], initial_allocation_fraction=fraction,
        rationale="Predeclared synthetic market reference for accounting checks")


def test_reference_is_one_purchase_after_known_close_with_frozen_fraction_and_costs():
    source = request_fixture()
    source.scenario.slippage_bps = D(10)
    request = equity_reference_request(source, reference(source))
    result = LocalReplayEngine().run(request)
    assert len(result.decisions) == len(result.fills) == 1
    fill = result.fills[0]
    assert fill.quantity == 4 and fill.price_usd == D("107.107") and fill.fee_usd == 1
    assert fill.signal_at.date() == date(2020, 1, 10) < fill.executed_at.date() == date(2020, 1, 13)
    assert result.equity[-1].cash_usd == D("570.572")
    assert result.equity[-1].equity_usd == D("1006.572")
    assert source.spec.risk.max_position_fraction == D(".4")
    request.end = date(2020, 1, 31)
    longer = LocalReplayEngine().run(request)
    assert len(longer.fills) == len(longer.decisions) == 1
    assert longer.equity[-1].quantities == {"etf_a": 4}


@pytest.mark.parametrize("missing", ["bar", "late", "mapping", "opening_gap"])
def test_reference_missing_or_unaffordable_entry_stays_explicit_without_later_retry(missing):
    source = request_fixture()
    request = equity_reference_request(source, reference(source))
    first = next(b for b in request.dataset.bars if b.session == source.start)
    if missing == "bar": request.dataset.bars.remove(first)
    elif missing == "late": first.available_at += timedelta(days=1)
    elif missing == "mapping": request.dataset.mappings[0].known_at += timedelta(days=20)
    else:
        for bar in request.dataset.bars:
            if bar.session > source.start:
                bar.open *= 10
                bar.high *= 10
                bar.low *= 10
                bar.close *= 10
    result = LocalReplayEngine().run(request)
    assert len(result.decisions) == 1 and not result.fills
    assert result.decisions[0].decision.status == ("targets" if missing == "opening_gap" else "no_signal")
    assert all(p.cash_usd == 1000 for p in result.equity)


def test_reference_preserves_split_income_and_delayed_payment_without_reinvestment():
    from tests.research.test_lean import changed_request
    source = changed_request("actions")
    request = equity_reference_request(source, reference(source, ".4"))
    result = LocalReplayEngine().run(request)
    assert len(result.fills) == 1
    assert {e.kind for e in result.events} >= {"split", "dividend", "payment", "cash_in_lieu", "delisting", "cash_yield"}
    assert result.equity[-1].quantities == {"etf_a": 0}
    assert result.equity[-1].cash_usd == result.equity[-1].equity_usd


def setup_reference_plan(repository, tmp_path):
    store, job, version = queue_fixture(repository, tmp_path)
    _, plan, manifest, specs = repository.inputs(job.experiment_id)
    repository.cancel(job.experiment_id)
    spec = specs[version.version_id]
    data = plan.model_dump()
    data["equity_reference"] = EquityReference(instrument=spec.universe[0], initial_allocation_fraction=".95", rationale="Synthetic equity reference with explicit cash balance")
    return store, manifest, specs, repository.freeze_plan(ResearchPlanInput.model_validate(data))


def test_all_reference_scenarios_are_persisted_and_report_cannot_drop_or_change_them(repository, tmp_path):
    store, manifest, specs, record = setup_reference_plan(repository, tmp_path)
    plan = ResearchPlanInput.model_validate(record.payload)
    result = evaluate(engine=LocalReplayEngine(), plan=plan, manifest=manifest, specs=specs, evaluation="development", inspected_trials=6, store=store)
    assert len(result.report["runs"]) == 12
    references = [r for r in result.report["runs"] if r["control"] == "equity_reference"]
    assert len(references) == 3 and all(r["metrics"]["fills"] == 1 for r in references)
    for run in result.report["runs"]:
        if run["control"] == "strategy":
            match = next(r for r in references if r["scenario"] == run["scenario"])
            assert run["equity_comparison"]["net_excess_return_fraction"] == pytest.approx(run["metrics"]["total_return_fraction"]-match["metrics"]["total_return_fraction"])
    job = repository.queue_experiment(ExperimentInput(plan_id=record.plan_id, snapshot_id=repository.list_snapshots()[0].snapshot_id, idempotency_key="reference"))
    repository.claim("reference-worker")
    corrupt = result.model_copy(deep=True)
    corrupt.report["runs"] = [r for r in corrupt.report["runs"] if r["control"] != "equity_reference"]
    corrupt.artifacts["report"] = content_hash(corrupt.report)
    with pytest.raises(ConflictError, match="every frozen control"):
        repository.finish(job.experiment_id, "reference-worker", result=corrupt)
    repository.finish(job.experiment_id, "reference-worker", result=result)
    assert repository.experiment(job.experiment_id).state == "completed"


def test_reference_requires_snapshot_coverage_before_consuming_trial(repository, tmp_path):
    _, _, _, record = setup_reference_plan(repository, tmp_path)
    payload = record.payload
    payload["equity_reference"]["instrument"]["instrument_id"] = "absent-reference"
    changed = repository.freeze_plan(ResearchPlanInput.model_validate(payload))
    before = repository.family_trial_count(changed.family_id)
    with pytest.raises(ConflictError, match="predeclared equity reference"):
        repository.queue_experiment(ExperimentInput(plan_id=changed.plan_id, snapshot_id=repository.list_snapshots()[0].snapshot_id, idempotency_key="missing-reference"))
    assert repository.family_trial_count(changed.family_id) == before


@pytest.mark.skipif(os.environ.get("TRADEMASTER_TEST_LEAN") != "1", reason="Explicit offline Docker integration suite")
def test_native_reference_matches_independent_hand_calculation_and_local_engine():
    source = request_fixture()
    source.scenario.slippage_bps = D(10)
    request = equity_reference_request(source, reference(source))
    native, local = LeanEngine().run(request), LocalReplayEngine().run(request)
    assert native.decisions == local.decisions
    assert len(native.venue_receipts) == 1 and native.venue_receipts[0].quantity == 4
    assert native.venue_receipts[0].price_usd == D("107.107")
    assert native.venue_equity[-1].equity_usd == local.equity[-1].equity_usd == D("1006.572")
