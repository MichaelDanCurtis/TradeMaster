"""Real process isolation and interruption; fabricated paper-account fixtures only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from tests.research.test_deployment import desk, action
from tests.research.test_deployment_jobs import queued, protocol_broker
from tradingagents.research.deployment_jobs import execute_job
from tradingagents.research.repository import ConflictError


SLOW_CHILD = '''
import json,os,sys,time
from pathlib import Path
import tradingagents.research.deployment_evaluation as evaluation
from tradingagents.research.deployment_child import main
original=evaluation.deployment_portfolio
def stalled(*args,**kwargs):
    Path(sys.argv[3]).write_text(json.dumps({"pid":os.getpid(),"sentinel":os.environ.get("TRADEMASTER_TEST_SENTINEL"),"dotenv":os.environ.get("PYTHON_DOTENV_DISABLED")}))
    time.sleep(60)
    return original(*args,**kwargs)
evaluation.deployment_portfolio=stalled
main(Path(sys.argv[1]),Path(sys.argv[2]))
'''


def test_pause_during_calculation_prevents_atomic_publication(desk, monkeypatch):
    from tradingagents.research.deployment_evaluation import DeploymentEvaluator
    import tradingagents.research.deployment_evaluation as module
    active, request, jobs, job, store = queued(desk, monkeypatch)
    jobs.claim(job.job_id, "pause-during-calculation")
    receipt, _ = desk[2]()
    original = module.deployment_portfolio
    def pause(*args, **kwargs):
        result = original(*args, **kwargs)
        jobs.pause(active.deployment_id, action(active))
        return result
    monkeypatch.setattr(module, "deployment_portfolio", pause)
    with pytest.raises(ConflictError):
        DeploymentEvaluator(jobs.sessions).evaluate(active.deployment_id, request, receipt.reconciliation_id,
            store, job_fence=(job.job_id, "pause-during-calculation"))
    detail = jobs.detail(active.deployment_id)
    assert detail["deployment"].state == "paused"
    assert not detail["evaluations"] and not detail["programs"]


def wait_marker(marker, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if marker.exists():
            try:
                return json.loads(marker.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(.02)
    raise AssertionError("Child never entered calculation")


def slow_process(monkeypatch, marker):
    import tradingagents.research.deployment_process as module
    original = subprocess.Popen
    processes = []
    def launch(command, **kwargs):
        process = original([sys.executable, "-c", SLOW_CHILD, *command[-2:], str(marker)], **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(module.subprocess, "Popen", launch)
    return processes


def test_cancel_stops_real_calculation_without_writer_lock_or_publication(desk, monkeypatch, tmp_path):
    active, _, jobs, job, store = queued(desk, monkeypatch)
    protocol_broker(desk[1], monkeypatch)
    monkeypatch.setenv("TRADEMASTER_TEST_SENTINEL", "must-not-reach-calculation")
    marker = tmp_path / "running.json"
    children = slow_process(monkeypatch, marker)
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(execute_job, jobs, job.job_id, lambda: desk[1], store)
        try:
            entry = wait_marker(marker)
            assert entry["sentinel"] is None and entry["dotenv"] == "1"
            started = time.monotonic()
            jobs.cancel(active.deployment_id, job.job_id, action(active))
            assert time.monotonic() - started < 2  # Slow calculation holds no writer lock.
            with pytest.raises(ConflictError):
                running.result(timeout=5)
        finally:
            for child in children:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
        assert children[0].poll() is not None
    detail = jobs.detail(active.deployment_id)
    assert jobs.get(job.job_id).state == "canceled" and detail["deployment"].state == "paused"
    assert not detail["evaluations"] and not detail["programs"] and not detail["orders"]
    assert desk[1].economic_orders == 0


def test_deadline_kills_real_calculation_and_recovers_without_retry(desk, monkeypatch, tmp_path):
    active, _, jobs, job, store = queued(desk, monkeypatch)
    protocol_broker(desk[1], monkeypatch)
    monkeypatch.setattr("tradingagents.research.deployment_jobs.RUNTIME_SECONDS", 2)
    marker = tmp_path / "deadline.json"
    children = slow_process(monkeypatch, marker)
    started = time.monotonic()
    with pytest.raises(ConflictError):
        execute_job(jobs, job.job_id, lambda: desk[1], store)
    assert time.monotonic() - started < 6 and marker.exists()
    assert children[0].poll() is not None
    assert jobs.get(job.job_id).state == "interrupted"
    assert jobs.detail(active.deployment_id)["deployment"].state == "paused"
    assert not jobs.detail(active.deployment_id)["evaluations"]
    assert execute_job(jobs, job.job_id, lambda: (_ for _ in ()).throw(AssertionError("No retry")), store)["failure"]


def test_killed_supervisor_pipe_terminates_child_and_preserves_recovery(desk, monkeypatch, tmp_path):
    active, _, jobs, job, store = queued(desk, monkeypatch)
    claimed, _ = jobs.claim(job.job_id, "supervisor-death")
    receipt, _ = desk[2]()
    marker = tmp_path / "orphan.json"
    wrapper = tmp_path / "supervisor.py"
    wrapper.write_text('''
import subprocess,sys
from pathlib import Path
from tradingagents.ui.db import create_session_factory
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.deployment_contracts import DeploymentEvaluationInput
from tradingagents.research.deployment_jobs import DeploymentJobs
from tradingagents.research.deployment_process import evaluate_in_process
original=subprocess.Popen
def launch(command,**kwargs):
    return original([sys.executable,"-c",SLOW_CHILD,*command[-2:],sys.argv[5]],**kwargs)
subprocess.Popen=launch
engine,sessions=create_session_factory(sys.argv[1])
job=DeploymentJobs(sessions).get(sys.argv[2])
evaluate_in_process(sessions,job.deployment_id,DeploymentEvaluationInput.model_validate(job.request),sys.argv[3],ArtifactStore(sys.argv[4]),job_fence=(job.job_id,job.owner))
'''.replace("original=subprocess.Popen", f"SLOW_CHILD={SLOW_CHILD!r}\noriginal=subprocess.Popen"))
    process = subprocess.Popen([sys.executable, str(wrapper), str(jobs.sessions.kw["bind"].url), job.job_id,
        receipt.reconciliation_id, str(store.root), str(marker)],
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(Path.cwd()), "PYTHON_DOTENV_DISABLED": "1"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    child_pid = None
    try:
        child_pid = wait_marker(marker)["pid"]
        process.kill()
        process.wait(timeout=5)
        end = time.monotonic() + 5
        while time.monotonic() < end:
            state = subprocess.run(["ps", "-o", "stat=", "-p", str(child_pid)], capture_output=True, text=True).stdout.strip()
            if not state or state.startswith("Z"):
                break
            time.sleep(.05)
        else:
            raise AssertionError("Calculation survived its killed supervisor")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if child_pid:
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    monkeypatch.setattr("tradingagents.research.deployment_jobs.now_utc", lambda: claimed.lease_until + timedelta(seconds=1))
    assert jobs.recover_expired()[0].state == "interrupted"
    assert jobs.detail(active.deployment_id)["deployment"].state == "paused"
    assert not jobs.detail(active.deployment_id)["evaluations"] and desk[1].economic_orders == 0
