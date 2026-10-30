"""Crash/lease tests use synthetic funding evidence and an isolated SQLite DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from tests.research.test_deployment import desk,activate,action,target_order
from tests.research.test_deployment_evaluation import current_fixture
from tradingagents.research.deployment_contracts import DeploymentEvaluationInput
from tradingagents.research.deployment_jobs import DeploymentJobs,execute_job,live_job
from tradingagents.research.deployment_evaluation import DeploymentEvaluator
from tradingagents.research.deployment_models import DeploymentEvaluationRecord,DeploymentEvaluationJob
from tradingagents.research.repository import ConflictError


def queued(desk,monkeypatch):
    active=activate(desk,monkeypatch)
    _,_,fresh,_,sessions,_,(research,store,_)=desk
    source,at=current_fixture(research,store)
    request=DeploymentEvaluationInput(**action(active).model_dump(),snapshot_id=source.snapshot_id,as_of=at)
    jobs=DeploymentJobs(sessions);job=jobs.enqueue(active.deployment_id,request)
    return active,request,jobs,job,store


def test_duplicate_queue_concurrent_claim_and_immutable_request(desk,monkeypatch):
    active,request,jobs,job,_=queued(desk,monkeypatch)
    assert jobs.enqueue(active.deployment_id,request).job_id==job.job_id
    def claim(owner):
        try: return jobs.claim(job.job_id,owner)[1]
        except ConflictError: return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim,["one","two"]))==[False,True]
    claimed=jobs.get(job.job_id)
    assert claimed.state=="running" and not jobs.recover_expired()
    with jobs.sessions() as session:
        with pytest.raises(IntegrityError,match="immutable"):
            session.execute(text("UPDATE research_deployment_jobs SET request_hash='replacement'"));session.commit()
    with pytest.raises(ConflictError,match="ownership"):
        jobs.heartbeat(job.job_id,"wrong-owner")


def test_expired_worker_is_fenced_and_recovery_is_idempotent(desk,monkeypatch):
    active,request,jobs,job,store=queued(desk,monkeypatch)
    claimed,_=jobs.claim(job.job_id,"worker")
    monkeypatch.setattr("tradingagents.research.deployment_jobs.now_utc",lambda:claimed.lease_until+timedelta(seconds=1))
    assert len(jobs.recover_expired())==1 and not jobs.recover_expired()
    assert jobs.get(job.job_id).state=="interrupted"
    assert jobs.detail(active.deployment_id)["deployment"].state=="paused"
    receipt,_=desk[2]()
    with pytest.raises(ConflictError,match="lease expired"):
        DeploymentEvaluator(jobs.sessions).evaluate(active.deployment_id,request,receipt.reconciliation_id,store,job_fence=(job.job_id,"worker"))
    with pytest.raises(ConflictError): jobs.finish(job.job_id,"worker",{"evaluation":"fabricated"})
    assert not jobs.detail(active.deployment_id)["evaluations"]


def test_runtime_deadline_cannot_be_extended_by_heartbeats(desk,monkeypatch):
    _,_,jobs,job,_=queued(desk,monkeypatch)
    claimed,_=jobs.claim(job.job_id,"worker")
    for seconds in (20,40,60,80,100,119):
        monkeypatch.setattr("tradingagents.research.deployment_jobs.now_utc",lambda seconds=seconds:claimed.started_at+timedelta(seconds=seconds))
        jobs.heartbeat(job.job_id,"worker")
    assert jobs.get(job.job_id).lease_until==claimed.deadline
    monkeypatch.setattr("tradingagents.research.deployment_jobs.now_utc",lambda:claimed.deadline)
    assert jobs.recover_expired()[0].state=="interrupted"


def test_pending_evaluation_blocks_old_entry_until_queue_is_explicitly_canceled(desk,monkeypatch):
    active=activate(desk,monkeypatch)
    boundary,order,_=target_order(desk,active)
    _,_,fresh,_,sessions,_,(research,store,_)=desk
    source,at=current_fixture(research,store)
    jobs=DeploymentJobs(sessions);job=jobs.enqueue(active.deployment_id,DeploymentEvaluationInput(**action(active).model_dump(),snapshot_id=source.snapshot_id,as_of=at))
    _,snapshot=fresh()
    with pytest.raises(ConflictError,match="Pending evaluation"):
        boundary.claim(order.order_id,snapshot)
    jobs.cancel(active.deployment_id,job.job_id,action(active))
    _,snapshot=fresh();_,claimed=boundary.claim(order.order_id,snapshot)
    assert claimed and jobs.detail(active.deployment_id)["deployment"].state=="paper_active"


def test_process_crash_after_publication_keeps_evidence_and_requires_review(desk,monkeypatch):
    active,request,jobs,job,store=queued(desk,monkeypatch)
    receipt,_=desk[2]()
    # Actual child exits after committing a proposal but before acknowledging
    # its job. No broker adapter or credential is available in this child.
    script='''
import os,sys
from tradingagents.ui.db import create_session_factory
from tradingagents.research.deployment_jobs import DeploymentJobs
from tradingagents.research.deployment_contracts import DeploymentEvaluationInput
from tradingagents.research.deployment_evaluation import DeploymentEvaluator
from tradingagents.research.data.store import ArtifactStore
engine,sessions=create_session_factory(sys.argv[1])
jobs=DeploymentJobs(sessions);job,_=jobs.claim(sys.argv[2],"crashing-worker")
DeploymentEvaluator(sessions).evaluate(job.deployment_id,DeploymentEvaluationInput.model_validate(job.request),sys.argv[3],ArtifactStore(sys.argv[4]),job_fence=(job.job_id,"crashing-worker"))
os._exit(7)
'''
    import os
    child=subprocess.run([sys.executable,"-c",script,str(jobs.sessions.kw["bind"].url),job.job_id,receipt.reconciliation_id,str(store.root)],
        env={"PATH":os.environ.get("PATH",""),"PYTHON_DOTENV_DISABLED":"1","PYTHONPATH":os.getcwd()},capture_output=True,text=True,timeout=20)
    assert child.returncode==7,child.stderr
    restarted=DeploymentJobs(jobs.sessions)
    assert len(restarted.detail(active.deployment_id)["evaluations"])==1
    assert not restarted.recover_expired()  # A restart alone cannot steal a live lease.
    claimed=restarted.get(job.job_id)
    monkeypatch.setattr("tradingagents.research.deployment_jobs.now_utc",lambda:claimed.lease_until+timedelta(seconds=1))
    restarted.recover_expired()
    detail=restarted.detail(active.deployment_id)
    assert detail["deployment"].state=="paused" and len(detail["evaluations"])==1 and len(detail["programs"])==1
    assert not detail["orders"] and desk[1].economic_orders==0
    result=execute_job(restarted,job.job_id,lambda:(_ for _ in ()).throw(AssertionError("must not reconstruct a broker")),store)
    assert result["failure"]["error_type"]=="InterruptedEvaluation"


def test_api_startup_recovers_expired_job_without_broker_calls(desk,monkeypatch):
    from fastapi.testclient import TestClient
    from tradingagents.ui.api import create_app
    active,_,jobs,job,_=queued(desk,monkeypatch)
    claimed,_=jobs.claim(job.job_id,"lost-worker")
    monkeypatch.setattr("tradingagents.research.deployment_jobs.now_utc",lambda:claimed.lease_until+timedelta(seconds=1))
    app=create_app(str(jobs.sessions.kw["bind"].url),broker_providers={"fixture-paper-broker":desk[1]})
    with TestClient(app):
        assert jobs.get(job.job_id).state=="interrupted"
        assert jobs.detail(active.deployment_id)["deployment"].state=="paused"
    assert desk[1].economic_orders==0


def protocol_broker(broker,monkeypatch):
    # Deliberately synthetic protocol metadata, never genuine provider evidence.
    snapshot=broker.paper_snapshot;activities=broker.account_activities
    monkeypatch.setattr(broker,"paper_snapshot",lambda:snapshot().model_copy(update={"evidence_kind":"broker_paper"}))
    monkeypatch.setattr(broker,"account_activities",lambda start,until:activities(start,until).model_copy(update={"evidence_kind":"broker_paper"}))


def test_worker_reconciles_and_completes_exactly_one_queued_proposal(desk,monkeypatch):
    from tradingagents.research.deployment_worker import maintenance_cycle
    active,_,jobs,job,store=queued(desk,monkeypatch)
    broker=desk[1];protocol_broker(broker,monkeypatch)
    first=maintenance_cycle(jobs.sessions,lambda:broker,store)
    assert first["status"]=="reconciled" and first["job"]["state"]=="completed"
    assert jobs.get(job.job_id).result["evaluation"]["payload"]["evaluation_job_id"]==job.job_id
    second=maintenance_cycle(jobs.sessions,lambda:broker,store)
    assert "job" not in second
    detail=jobs.detail(active.deployment_id)
    assert len(detail["evaluations"])==1 and len(detail["programs"])==1
    assert not detail["orders"] and broker.economic_orders==0


def test_worker_recovers_lost_native_acknowledgment_without_posting(desk,monkeypatch):
    from tradingagents.research.deployment_worker import maintenance_cycle
    active=activate(desk,monkeypatch)
    boundary,order,exact=target_order(desk,active)
    _,snapshot=desk[2]();attempt,_=boundary.claim(order.order_id,snapshot)
    broker=desk[1];broker.submit_exact_order(order.intent_id,exact)
    # Submission succeeded remotely, but its acknowledgment was never saved.
    assert boundary.attempt_for_order(order.order_id).state=="dispatching"
    protocol_broker(broker,monkeypatch)
    result=maintenance_cycle(desk[4],lambda:broker,desk[6][1],process_job=False)
    assert result["status"]=="reconciled"
    assert boundary.attempt_for_order(order.order_id).state=="accepted"
    assert broker.economic_orders==1


def test_cancel_running_job_fences_failure_and_success_publication(desk,monkeypatch):
    active,request,jobs,job,store=queued(desk,monkeypatch)
    jobs.claim(job.job_id,"worker")
    jobs.cancel(active.deployment_id,job.job_id,action(active))
    assert jobs.detail(active.deployment_id)["deployment"].state=="paused"
    with pytest.raises(ConflictError,match="ownership"):
        jobs.evaluation_failed(active.deployment_id,request,"late_failure","TimeoutError",job_fence=(job.job_id,"worker"))
    with pytest.raises(ConflictError): jobs.finish(job.job_id,"worker",{})
    assert jobs.get(job.job_id).state=="canceled"


def test_unused_worker_does_not_construct_a_broker(tmp_path):
    from tradingagents.research.deployment_worker import maintenance_cycle
    from tradingagents.ui.db import create_session_factory,init_db
    from tradingagents.research.data.store import ArtifactStore
    engine,sessions=create_session_factory(f"sqlite:///{tmp_path/'unused.db'}");init_db(engine)
    result=maintenance_cycle(sessions,lambda:(_ for _ in ()).throw(AssertionError("No broker access")),ArtifactStore(tmp_path/'artifacts'))
    assert result["status"]=="baseline_review_required"
    engine.dispose()


def test_lease_expiring_during_calculation_rolls_back_all_proposals(desk,monkeypatch):
    import tradingagents.research.deployment_evaluation as module
    active,request,jobs,job,store=queued(desk,monkeypatch)
    claimed,_=jobs.claim(job.job_id,"slow-worker")
    calculate=module.deployment_portfolio
    def expired_calculation(*args,**kwargs):
        result=calculate(*args,**kwargs)
        monkeypatch.setattr("tradingagents.research.deployment_jobs.now_utc",lambda:claimed.lease_until)
        return result
    monkeypatch.setattr(module,"deployment_portfolio",expired_calculation)
    receipt,_=desk[2]()
    with pytest.raises(ConflictError,match="lease expired"):
        DeploymentEvaluator(jobs.sessions).evaluate(active.deployment_id,request,receipt.reconciliation_id,store,job_fence=(job.job_id,"slow-worker"))
    detail=jobs.detail(active.deployment_id)
    assert not detail["evaluations"] and not detail["programs"]
    assert jobs.recover_expired()[0].state=="interrupted"


def test_queue_api_permissions_cancellation_and_terminal_duplicate(desk,monkeypatch):
    from fastapi.testclient import TestClient
    from tradingagents.ui.api import create_app
    active=activate(desk,monkeypatch)
    source,at=current_fixture(desk[6][0],desk[6][1])
    request=DeploymentEvaluationInput(**action(active).model_dump(),snapshot_id=source.snapshot_id,as_of=at)
    app=create_app(str(desk[4].kw["bind"].url),broker_providers={"fixture-paper-broker":desk[1]})
    path=f"/api/research/deployments/{active.deployment_id}/evaluation-jobs"
    with TestClient(app) as client:
        assert client.post(path,json=request.model_dump(mode="json"),headers={"X-Trademaster-Room":"research"}).status_code==403
        assert not DeploymentJobs(desk[4]).detail(active.deployment_id)["evaluation_jobs"]
        headers={"X-Trademaster-Room":"market"}
        result=client.post(path,json=request.model_dump(mode="json"),headers=headers)
        assert result.status_code==202
        job=result.json()["job"]
        canceled=client.post(f'{path}/{job["job_id"]}/cancel',json=action(active).model_dump(mode="json"),headers=headers)
        assert canceled.status_code==200 and canceled.json()["job"]["state"]=="canceled"
        repeated=client.post(path,json=request.model_dump(mode="json"),headers=headers).json()
        assert repeated["job"]["job_id"]==job["job_id"] and "No duplicate" in repeated["message"]
    assert desk[1].economic_orders==0
