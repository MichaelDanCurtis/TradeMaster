"""Opt-in deployment evaluation worker with read-only broker reconciliation.

Work is queued with pinned source/cutoff/funding via the deployment API. This
process cannot approve orders or invoke submission. It may cancel stale entries.
"""
import argparse
import json
import os
from pathlib import Path

from sqlmodel import select

from tradingagents.research.accounting_worker import reconcile_configured_account
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.deployment_jobs import DeploymentJobs,execute_job
from tradingagents.research.deployment_models import DeploymentEvaluationJob
from tradingagents.research.deployment_service import DeploymentService
from tradingagents.research.execution_repository import account_key
from tradingagents.research.repository import ConflictError


def maintenance_cycle(sessions,broker_resolver,store,*,process_job=True,progress=None,cycle_id=None):
    jobs=DeploymentJobs(sessions)
    recovered=jobs.recover_expired()
    # Do not construct a broker in an unused installation.
    from tradingagents.research.accounting_models import PaperEnrollmentRecord
    with sessions() as session:
        if session.exec(select(PaperEnrollmentRecord)).first() is None:
            return {"status":"baseline_review_required","recovered":[j.job_id for j in recovered]}
    try:
        broker=broker_resolver()
        identity=broker.paper_identity() if callable(getattr(broker,"paper_identity",None)) else broker.paper_snapshot()
        key=account_key(identity)
        if progress: progress("observing",account_key=key)
        observation=reconcile_configured_account(sessions,broker)
    except Exception as exc:
        from tradingagents.ui.brokers.alpaca import SnapshotConsistencyError
        details = {"message": str(exc), "snapshot_diagnostics": exc.diagnostics} if isinstance(exc, SnapshotConsistencyError) else {}
        return {"status":"observation_unavailable","error_type":type(exc).__name__,**details,"recovered":[j.job_id for j in recovered]}
    service=DeploymentService(sessions,broker)
    if progress: progress("canceling",account_key=key)
    cancellations=[]
    # Recovery can have happened in the API process. Inspect retained paused
    # deployments every cycle so a failed cancellation gets another lookup/cancel.
    for record in jobs.list():
        if record.account_key==key and record.state=="paused":
            cancellations.extend(service.cancel_entries(record,"deployment-supervisor")["cancellations"])
    result={"status":observation["status"],"account":observation,"recovered":[j.job_id for j in recovered],"cancellations":cancellations}
    if not process_job or observation["status"]!="reconciled" or not observation["drawdown_available"]: return result
    with sessions() as session:
        job=session.exec(select(DeploymentEvaluationJob).where(DeploymentEvaluationJob.account_key==key)
            .where(DeploymentEvaluationJob.state=="queued").order_by(DeploymentEvaluationJob.created_at,DeploymentEvaluationJob.job_id)).first()
    if job:
        try:
            if progress: progress("evaluating",account_key=key,job_id=job.job_id)
            execute_job(jobs,job.job_id,lambda:broker,store,cycle_id=cycle_id)
            result["job"]={"job_id":job.job_id,"state":jobs.get(job.job_id).state}
        except ConflictError:
            result["job"]={"job_id":job.job_id,"state":jobs.get(job.job_id).state}
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url",required=True)
    parser.add_argument("--artifacts",type=Path)
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--interval-seconds",type=int,default=15)
    parser.add_argument("--reconcile-only",action="store_true")
    parser.add_argument("--cycle-timeout-seconds",type=int,default=180)
    args=parser.parse_args()
    if not 5<=args.interval_seconds<=300: parser.error("interval must be between 5 and 300 seconds")
    if not 10<=args.cycle_timeout_seconds<=600: parser.error("cycle timeout must be between 10 and 600 seconds")
    from tradingagents.ui.db import create_session_factory,init_db
    from tradingagents.research.deployment_supervisor import DeploymentSupervisor
    from dotenv import load_dotenv
    load_dotenv()
    engine,sessions=create_session_factory(args.database_url);init_db(engine)
    database=engine.url.database
    if engine.url.get_backend_name()!="sqlite" or not database or database==":memory:":
        parser.error("a persistent SQLite database is required")
    root=args.artifacts or os.environ.get("TRADEMASTER_RESEARCH_ARTIFACTS") or (Path(database).resolve().parent/".research-artifacts" if database and database!=":memory:" else Path.cwd()/".research-artifacts")
    store=ArtifactStore(root)
    supervisor=DeploymentSupervisor(sessions,store,process_job=not args.reconcile_only,
        interval_seconds=args.interval_seconds,cycle_timeout_seconds=args.cycle_timeout_seconds)
    try:
        while True:
            result=supervisor.run_once()
            print(json.dumps(result),flush=True)
            if args.once: return
            supervisor.wait_interval()
    except KeyboardInterrupt: return
    finally:
        supervisor.close()
        engine.dispose()


if __name__=="__main__": main()
