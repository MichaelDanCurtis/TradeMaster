from datetime import date, timedelta
from decimal import Decimal as D
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
import time

import pytest

from tradingagents.research.contracts import canonical_json
from tradingagents.research.data.contracts import CorporateAction
from tradingagents.research.engines.lean import LeanEngine, clock_times, export_inputs, docker_path, cleanup_container
from tradingagents.research.engines.replay import LocalReplayEngine
from tests.research.test_replay import request_fixture, proportional_request
from tests.research.test_guidance_replay import request as guidance_request
from tests.research.test_worker import queue_fixture
from tradingagents.research.worker import ResearchWorker


def test_export_uses_explicit_calendar_and_never_releases_close_in_opening_price(tmp_path):
    request = request_fixture()
    export_inputs(request, tmp_path, "test-build")
    rows = (tmp_path/"I0000.csv").read_text().splitlines()
    assert "2020-01-13T14:30:00.000000,107" in rows
    assert "2020-01-13T21:00:00.000000,108" in rows
    assert all("2020-01-11" not in row for row in rows)
    assert clock_times(request)[0] == next(s.opens_at for s in request.dataset.sessions if s.date == request.start)
    payload = json.loads((tmp_path/"request.json").read_text())
    assert payload["symbols"] == {"etf_a": "I0000"}
    assert "broker" not in payload


def changed_request(case):
    if case == "proportional": return proportional_request()
    request = request_fixture()
    request.scenario.slippage_bps = D(10)
    if case == "gap":
        for bar in request.dataset.bars:
            if bar.session >= date(2020, 1, 13):
                for name in ("open", "high", "low", "close"): setattr(bar, name, getattr(bar, name)*3)
    elif case == "missing":
        request.dataset.bars = [b for b in request.dataset.bars if b.session != date(2020, 1, 14)]
    elif case == "holiday":
        request.start, request.end = date(2020, 1, 17), date(2020, 1, 23)
        request.scenario.execution_delay_sessions = 1
    elif case == "actions":
        request.end = date(2020, 1, 17)
        request.cash_annual_yield_fraction = D(".03")
        split = next(s for s in request.dataset.sessions if s.date == date(2020, 1, 14))
        dividend = next(s for s in request.dataset.sessions if s.date == date(2020, 1, 15))
        delist = next(s for s in request.dataset.sessions if s.date == date(2020, 1, 17))
        request.dataset.actions = [
            CorporateAction(action_id="split", instrument_id="etf_a", kind="split", effective_session=split.date, available_at=split.opens_at, split_ratio=D("1.5")),
            CorporateAction(action_id="dividend", instrument_id="etf_a", kind="dividend", effective_session=dividend.date, available_at=dividend.opens_at, cash_per_share_usd=1, payable_at=dividend.closes_at+timedelta(days=1)),
            CorporateAction(action_id="delist", instrument_id="etf_a", kind="delisting", effective_session=delist.date, available_at=delist.opens_at, cash_per_share_usd=60, payable_at=delist.closes_at),
        ]
        for bar in request.dataset.bars:
            if bar.session >= split.date:
                for name in ("open", "high", "low", "close"): setattr(bar, name, (getattr(bar, name)/D("1.5")).quantize(D(".000001")))
    elif case.startswith("guidance_"):
        request = guidance_request(case.removeprefix("guidance_"))
    return request


@pytest.mark.skipif(os.environ.get("TRADEMASTER_TEST_LEAN") != "1", reason="Explicit offline Docker integration suite")
@pytest.mark.parametrize("case", ["base", "proportional", "gap", "missing", "holiday", "actions", "guidance_guidance_control", "guidance_numeric_quality", "guidance_astra_challenger"])
def test_native_lean_reconciles_and_matches_shared_strategy_targets(tmp_path, case):
    request = changed_request(case)
    local = LocalReplayEngine().run(request)
    native = LeanEngine(output_directory=tmp_path/case).run(request)
    assert native.engine_build.startswith("lean-v1-")
    assert native.decisions == local.decisions
    assert len(native.venue_receipts) == len(native.fills) == len(local.fills)
    assert len(native.venue_equity) == len(native.equity) == len(local.equity)
    for fill, expected, receipt in zip(native.fills, local.fills, native.venue_receipts):
        assert (fill.instrument_id, fill.quantity, fill.signal_at, fill.executed_at, fill.observed_at) == (expected.instrument_id, expected.quantity, expected.signal_at, expected.executed_at, expected.observed_at)
        assert fill.signal_at < fill.executed_at == receipt.at <= fill.observed_at
        assert abs(fill.price_usd - expected.price_usd) < D(".000001")
        assert fill.fee_usd == expected.fee_usd == receipt.fee_usd
    for point, expected, actual in zip(native.equity, local.equity, native.venue_equity):
        assert point.quantities == expected.quantities == actual.quantities
        for name in ("equity_usd", "cash_usd", "receivables_usd", "cost_basis_usd"):
            assert abs(getattr(point, name)-getattr(expected, name)) < D(".000001")
            assert abs(getattr(point, name)-getattr(actual, name)) < D(".000001")
    if case == "base":
        assert native.fills[0].quantity == 3 and native.fills[0].price_usd == D("107.107")
        assert native.equity[-1].equity_usd == D("1004.679")
        repeated = LeanEngine().run(request)
        assert canonical_json(repeated) == canonical_json(native)
    elif case == "gap": assert not native.fills
    elif case == "missing": assert native.equity[-1].stale_instruments == ["etf_a"]
    elif case == "holiday": assert native.fills[0].executed_at.date() == date(2020, 1, 22)
    elif case == "actions":
        assert native.equity[-1].quantities == {"etf_a": 0}
        assert {e.kind for e in native.events} >= {"split", "dividend", "payment", "cash_in_lieu", "delisting", "cash_yield"}
    if case.startswith("guidance_"):
        from tradingagents.research.evaluation.paired_events import attribute_events
        left=attribute_events(request.dataset,request.spec,local)
        right=attribute_events(request.dataset,request.spec,native)
        assert left["outcomes"].keys()==right["outcomes"].keys()
        assert abs(left["event_pnl_usd"]-right["event_pnl_usd"])<D(".000001")
        for notice in left["outcomes"]:
            assert left["outcomes"][notice]["state"]==right["outcomes"][notice]["state"]


def is_running(name):
    response = subprocess.run([docker_path(), "inspect", "--format", "{{.State.Running}}", name], capture_output=True, text=True, timeout=5)
    return response.returncode == 0 and response.stdout.strip() == "true"


def wait_for_container(name_file):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if name_file.exists():
            name = name_file.read_text()
            if is_running(name): return name
        time.sleep(.1)
    raise AssertionError("Native research container did not start")


@pytest.mark.skipif(os.environ.get("TRADEMASTER_TEST_LEAN") != "1", reason="Explicit offline Docker integration suite")
def test_durable_worker_runs_all_native_control_paths(repository, tmp_path):
    store, job, _ = queue_fixture(repository, tmp_path, engine="lean", timeout=180)
    ResearchWorker(repository, store).run_once()
    result = repository.experiment(job.experiment_id)
    assert result.state == "completed", result.failure_reason
    assert result.result["engine_build"].startswith("lean-v1-")
    assert result.result["evidence_status"] == "fixture_only"
    assert len(result.result["report"]["runs"]) == 9
    for summary in result.result["report"]["runs"]:
        artifact = store.json(summary["artifact_hash"])
        assert len(artifact["venue_equity"]) == summary["metrics"]["observations"]
        assert len(artifact["venue_receipts"]) == summary["metrics"]["fills"]


@pytest.mark.skipif(os.environ.get("TRADEMASTER_TEST_LEAN") != "1", reason="Explicit offline Docker integration suite")
def test_cancelled_native_worker_removes_its_container(repository, tmp_path, monkeypatch):
    store, job, _ = queue_fixture(repository, tmp_path, engine="lean", timeout=180)
    name_file = tmp_path/"container-name"
    original = LeanEngine.__init__
    def observe(self, **kwargs):
        original(self, **kwargs)
        name_file.write_text(self.container_name)
    monkeypatch.setattr(LeanEngine, "__init__", observe)
    worker = ResearchWorker(repository, store)
    thread = Thread(target=worker.run_once)
    thread.start()
    name = None
    try:
        name = wait_for_container(name_file)
        repository.cancel(job.experiment_id)
        thread.join(timeout=15)
        assert not thread.is_alive() and not is_running(name)
        assert repository.experiment(job.experiment_id).state == "cancelled"
    finally:
        repository.cancel(job.experiment_id)
        if name: cleanup_container(name)
        thread.join(timeout=15)


@pytest.mark.skipif(os.environ.get("TRADEMASTER_TEST_LEAN") != "1", reason="Explicit offline Docker integration suite")
def test_supervisor_crash_closes_private_pipe_and_stops_native_container(repository, tmp_path):
    store, job, _ = queue_fixture(repository, tmp_path, engine="lean", timeout=180)
    name_file = tmp_path/"crashed-container"
    script = '''
import sys
from pathlib import Path
from tradingagents.research.engines.lean import LeanEngine
from tradingagents.research.worker import ResearchWorker
from tradingagents.research.repository import ResearchRepository
from tradingagents.research.data.store import ArtifactStore
from tradingagents.ui.db import create_session_factory
original = LeanEngine.__init__
def observe(self, **kwargs):
    original(self, **kwargs)
    Path(sys.argv[3]).write_text(self.container_name)
LeanEngine.__init__ = observe
_, sessions = create_session_factory(sys.argv[1])
ResearchWorker(ResearchRepository(sessions), ArtifactStore(Path(sys.argv[2])), worker_id="crash-test").run_once()
'''
    name = None
    with (tmp_path/"supervisor.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-c", script, str(repository.sessions.kw["bind"].url), str(store.root), str(name_file)], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            name = wait_for_container(name_file)
            process.kill()
            process.wait(timeout=5)
            deadline = time.monotonic()+15
            while is_running(name) and time.monotonic() < deadline: time.sleep(.1)
            assert not is_running(name), "Detached LEAN container survived supervisor death"
            assert repository.experiment(job.experiment_id).result is None
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=5)
            if name: cleanup_container(name)
            repository.cancel(job.experiment_id)
