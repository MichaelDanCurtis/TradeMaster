"""Supervisor process tests use disposable SQLite stores and synthetic providers."""
from datetime import timedelta
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from tests.research.test_deployment import desk
from tests.research.test_deployment_jobs import queued
from tests.research.test_deployment_process import wait_marker
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.deployment_health import DeploymentHealth
from tradingagents.research.deployment_supervisor import DeploymentSupervisor, cycle_environment
from tradingagents.research.repository import ConflictError
from tradingagents.ui.db import create_session_factory,init_db


def test_health_scope_mode_staleness_and_late_child_updates(tmp_path,monkeypatch):
    engine,sessions=create_session_factory(f"sqlite:///{tmp_path/'health.db'}");init_db(engine)
    health=DeploymentHealth(sessions)
    assert not health.runtime()["connected"]
    health.register("one",mode="reconcile_only",interval_seconds=15,cycle_timeout_seconds=180)
    health.start_cycle("one","first")
    health.progress("one","first","observing",account_key="account-a")
    scoped=health.runtime("account-a")
    assert scoped["connected"] and not scoped["evaluation_worker_connected"] and not scoped["order_authority"]
    assert not health.runtime("account-b")["connected"]
    from tradingagents.research.deployment_models import DeploymentWorkerRecord
    with sessions() as session: seen=session.get(DeploymentWorkerRecord,"one").last_seen_at
    monkeypatch.setattr("tradingagents.research.deployment_health.now_utc",lambda:seen+timedelta(seconds=21))
    assert not health.runtime()["connected"] and health.runtime()["workers"][0]["status"]=="stale"
    health.heartbeat("one")
    health.finish_cycle("one","first",{"status":"reconciled"})
    health.start_cycle("one","second")
    with pytest.raises(ConflictError):health.progress("one","first","evaluating",account_key="account-a")
    health.stop("one")
    assert health.runtime()["workers"][0]["status"]=="stopped" and not health.runtime()["connected"]
    with pytest.raises(ConflictError):health.heartbeat("one")
    engine.dispose()


def test_child_receives_only_selected_environment_credential(tmp_path,monkeypatch):
    from tradingagents.ui.repository import UiRepository
    engine,sessions=create_session_factory(f"sqlite:///{tmp_path/'env.db'}");init_db(engine)
    UiRepository(sessions).upsert_provider_config("alpaca-paper-broker",enabled=True,secret_ref="env:TEST_PAPER_ONLY")
    monkeypatch.setenv("TEST_PAPER_ONLY","synthetic-value")
    monkeypatch.setenv("UNRELATED_MODEL_SECRET","must-not-forward")
    env=cycle_environment(sessions)
    assert env["TEST_PAPER_ONLY"]=="synthetic-value" and "UNRELATED_MODEL_SECRET" not in env
    assert env["PYTHON_DOTENV_DISABLED"]=="1" and env["TRADEMASTER_ENABLE_REAL_RUNS"]=="0"
    engine.dispose()


def test_actual_cli_unused_installation_records_stopped_health_without_provider(tmp_path):
    database=f"sqlite:///{tmp_path/'empty.db'}"
    process=subprocess.run([sys.executable,"-m","tradingagents.research.deployment_worker","--database-url",database,"--once"],
        cwd=Path.cwd(),env={"PATH":os.environ.get("PATH",""),"HOME":str(tmp_path),"PYTHON_DOTENV_DISABLED":"1"},
        capture_output=True,text=True,timeout=20)
    assert process.returncode==0,process.stderr
    assert json.loads(process.stdout)["status"]=="baseline_review_required"
    engine,sessions=create_session_factory(database)
    runtime=DeploymentHealth(sessions).runtime()
    assert not runtime["connected"] and runtime["workers"][0]["status"]=="stopped"
    assert runtime["workers"][0]["last_result"]["status"]=="baseline_review_required"
    engine.dispose()


def test_enrolled_but_unconfigured_provider_is_not_replaced_with_fixture(desk):
    supervisor=DeploymentSupervisor(desk[4],desk[6][1])
    try:
        result=supervisor.run_once()
        assert result["status"]=="observation_unavailable" and result["error_type"]=="HTTPException"
        worker=supervisor.health.runtime()["workers"][0]
        assert worker["connected"] and worker["status"]=="attention" and worker["account_key"] is None
    finally:supervisor.close()


COMPLETE_CHILD='''
import sys
from pathlib import Path
import tradingagents.research.deployment_cycle_child as child
from tradingagents.ui.brokers.fake import FakePaperBroker
broker=FakePaperBroker()
snapshot=broker.paper_snapshot;activities=broker.account_activities
broker.paper_snapshot=lambda:snapshot().model_copy(update={"evidence_kind":"broker_paper"})
broker.account_activities=lambda start,until:activities(start,until).model_copy(update={"evidence_kind":"broker_paper"})
child.resolve_configured_broker=lambda sessions:broker
child.main(Path(sys.argv[1]),Path(sys.argv[2]))
assert broker.economic_orders==0
'''

SLOW_CYCLE='''
import json,os,sys,time
from pathlib import Path
import tradingagents.research.deployment_worker as worker
from tradingagents.research.deployment_jobs import DeploymentJobs
from tradingagents.research.deployment_models import DeploymentEvaluationJob
from sqlmodel import select
from tradingagents.research.deployment_cycle_child import main
def stall(sessions,resolver,store,*,progress,cycle_id,**kwargs):
    jobs=DeploymentJobs(sessions)
    with sessions() as session:
        job=session.exec(select(DeploymentEvaluationJob).where(DeploymentEvaluationJob.state=="queued")).first()
    if job:
        jobs.claim(job.job_id,cycle_id+":stalled")
        progress("evaluating",account_key=job.account_key,job_id=job.job_id)
    Path(sys.argv[3]).write_text(json.dumps({"pid":os.getpid()}))
    time.sleep(60)
worker.maintenance_cycle=stall
main(Path(sys.argv[1]),Path(sys.argv[2]))
'''


def injected_cycle(monkeypatch,script,marker=None):
    original=subprocess.Popen;children=[]
    def launch(command,**kwargs):
        process=original([sys.executable,"-c",script,*command[-2:],*([str(marker)] if marker else [])],**kwargs)
        children.append(process)
        return process
    monkeypatch.setattr("tradingagents.research.deployment_supervisor.subprocess.Popen",launch)
    return children


def test_real_cycle_reconciles_and_runs_nested_calculation_without_orders(desk,monkeypatch):
    active,_,jobs,job,store=queued(desk,monkeypatch)
    injected_cycle(monkeypatch,COMPLETE_CHILD)
    supervisor=DeploymentSupervisor(jobs.sessions,store)
    try:
        result=supervisor.run_once()
        assert result["status"]=="reconciled" and result["job"]["state"]=="completed"
        assert jobs.get(job.job_id).owner.startswith("dcycle_")
        runtime=supervisor.health.runtime(active.account_key)
        assert runtime["evaluation_worker_connected"] and runtime["workers"][0]["last_result"]["account"]["drawdown_available"]
        detail=jobs.detail(active.deployment_id)
        assert len(detail["evaluations"])==1 and len(detail["programs"])==1 and not detail["orders"]
    finally:supervisor.close()


def test_timeout_terminates_cycle_and_only_interrupts_its_owned_job(desk,monkeypatch,tmp_path):
    active,_,jobs,job,store=queued(desk,monkeypatch)
    marker=tmp_path/"stalled.json"
    children=injected_cycle(monkeypatch,SLOW_CYCLE,marker)
    supervisor=DeploymentSupervisor(jobs.sessions,store,cycle_timeout_seconds=10)
    # Test-only acceleration; production CLI validates a minimum ten seconds.
    supervisor.cycle_timeout_seconds=2
    try:
        result=supervisor.run_once()
        assert result["status"]=="cycle_failed" and marker.exists() and children[0].poll() is not None
        saved=jobs.get(job.job_id)
        assert saved.state=="interrupted" and saved.result["failure"]["stage"]=="cycle_termination"
        assert jobs.detail(active.deployment_id)["deployment"].state=="paused"
        assert not jobs.detail(active.deployment_id)["evaluations"]
        # A different, unexpired claim must not be stolen by cycle cleanup.
        from tests.research.test_deployment import activate,action
        from tests.research.test_deployment_evaluation import current_fixture
        from tradingagents.research.deployment_contracts import DeploymentEvaluationInput
        second=activate(desk,monkeypatch,key="other-worker")
        source,at=current_fixture(desk[6][0],store)
        other=jobs.enqueue(second.deployment_id,DeploymentEvaluationInput(**action(second).model_dump(),snapshot_id=source.snapshot_id,as_of=at))
        jobs.claim(other.job_id,"another-worker")
        assert not jobs.recover_expired(stopped_cycle_id="dcycle_"+"a"*32)
        assert jobs.get(other.job_id).state=="running"
    finally:supervisor.close()


def test_runtime_api_is_read_only_and_checks_room_access(desk):
    from fastapi.testclient import TestClient
    from tradingagents.ui.api import create_app
    health=DeploymentHealth(desk[4]);health.register("observer",mode="evaluate",interval_seconds=15,cycle_timeout_seconds=180)
    with TestClient(create_app(str(desk[4].kw["bind"].url))) as client:
        response=client.get("/api/research/deployments/runtime",headers={"X-Trademaster-Room":"research"})
        assert response.status_code==200 and response.json()["evaluation_worker_connected"]
        assert client.get("/api/research/deployments/runtime",headers={"X-Trademaster-Room":"unknown-room"}).status_code==403
    assert desk[1].economic_orders==0


def test_killed_supervisor_stops_provider_cycle_and_heartbeat_goes_stale(desk,monkeypatch,tmp_path):
    active,_,jobs,job,store=queued(desk,monkeypatch)
    marker=tmp_path/"orphan-cycle.json"
    wrapper=tmp_path/"supervisor.py"
    wrapper.write_text('''
import subprocess,sys
from tradingagents.ui.db import create_session_factory
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.deployment_supervisor import DeploymentSupervisor
original=subprocess.Popen
def launch(command,**kwargs):
    return original([sys.executable,"-c",SLOW_CYCLE,*command[-2:],sys.argv[3]],**kwargs)
subprocess.Popen=launch
engine,sessions=create_session_factory(sys.argv[1])
DeploymentSupervisor(sessions,ArtifactStore(sys.argv[2])).run_once()
'''.replace("original=subprocess.Popen",f"SLOW_CYCLE={SLOW_CYCLE!r}\noriginal=subprocess.Popen"))
    process=subprocess.Popen([sys.executable,str(wrapper),str(jobs.sessions.kw["bind"].url),str(store.root),str(marker)],
        env={"PATH":os.environ.get("PATH",""),"PYTHONPATH":str(Path.cwd()),"HOME":str(tmp_path),"PYTHON_DOTENV_DISABLED":"1"},
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    child_pid=None
    try:
        child_pid=wait_marker(marker)["pid"]
        process.kill();process.wait(timeout=5)
        end=time.monotonic()+5
        while time.monotonic()<end:
            state=subprocess.run(["ps","-o","stat=","-p",str(child_pid)],capture_output=True,text=True).stdout.strip()
            if not state or state.startswith("Z"):break
            time.sleep(.05)
        else:raise AssertionError("Provider cycle survived supervisor death")
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=5)
        if child_pid:
            try:os.killpg(child_pid,signal.SIGKILL)
            except ProcessLookupError:pass
    claimed=jobs.get(job.job_id)
    monkeypatch.setattr("tradingagents.research.deployment_health.now_utc",lambda:claimed.lease_until+timedelta(seconds=1))
    assert not DeploymentHealth(jobs.sessions).runtime()["connected"]
    monkeypatch.setattr("tradingagents.research.deployment_jobs.now_utc",lambda:claimed.lease_until+timedelta(seconds=1))
    assert jobs.recover_expired()[0].state=="interrupted"
    assert jobs.detail(active.deployment_id)["deployment"].state=="paused"
    assert not jobs.detail(active.deployment_id)["evaluations"]
