"""Durable bounded evaluation work. No order approval or broker submission."""
from datetime import timedelta,timezone
from threading import Event,Thread
from uuid import uuid4

from sqlalchemy import text
from sqlmodel import select

from tradingagents.research.contracts import content_hash
from tradingagents.research.deployment_contracts import DeploymentEvaluationInput
from tradingagents.research.deployment_models import DeploymentEvaluationJob,StrategyDeploymentRecord
from tradingagents.research.deployment_repository import DeploymentRepository
from tradingagents.research.repository import ConflictError,require
from tradingagents.ui.models import now_utc

LEASE_SECONDS=30
RUNTIME_SECONDS=120
MAX_QUEUED=100
TERMINAL={"completed","failed","conflict","interrupted","canceled"}


def live_job(session,job_id,owner):
    job=require(session,DeploymentEvaluationJob,job_id)
    now=now_utc()
    if job.state!="running" or job.owner!=owner or job.lease_until is None or job.deadline is None or now>=min(job.lease_until,job.deadline):
        raise ConflictError("Evaluation lease expired or ownership changed; this worker cannot publish")
    return job


class DeploymentJobs(DeploymentRepository):
    def enqueue(self,identifier,request):
        with self.transaction() as session:
            record=require(session,StrategyDeploymentRecord,identifier)
            # Revision binds the recovery review; equivalent timezone syntax is
            # one request. Actor/reason are retained from the first submission.
            digest=content_hash({"deployment_id":identifier,"revision":request.expected_revision,
                "snapshot_id":request.snapshot_id,"as_of":request.as_of.astimezone(timezone.utc).isoformat()})
            existing=session.exec(select(DeploymentEvaluationJob).where(DeploymentEvaluationJob.request_hash==digest)).first()
            if existing: return existing
            self._revision(record,request)
            if record.state!="paper_active" or not record.active_terms_id:
                raise ConflictError("Only an active reviewed deployment can queue evaluation")
            from tradingagents.research.models import DatasetSnapshotRecord
            source=require(session,DatasetSnapshotRecord,request.snapshot_id)
            if source.evidence_kind!="prospective" or request.as_of>now_utc():
                raise ConflictError("Evaluation needs a prospective snapshot and a nonfuture cutoff")
            pending=list(session.exec(select(DeploymentEvaluationJob).where(DeploymentEvaluationJob.state.in_(["queued","running"]))))
            if any(j.deployment_id==identifier for j in pending):
                raise ConflictError("This deployment already has pending evaluation work")
            if len(pending)>=MAX_QUEUED: raise ConflictError("Deployment evaluation queue is full")
            job=DeploymentEvaluationJob(deployment_id=identifier,terms_id=record.active_terms_id,account_key=record.account_key,
                request_hash=digest,request=request.model_dump(mode="json"))
            session.add(job)
            self._event(session,record,"evaluation_queued",request.actor,request.reason,{"job_id":job.job_id,"request_hash":digest})
        return job

    def get(self,identifier):
        with self.sessions() as session: return require(session,DeploymentEvaluationJob,identifier)

    def claim(self,identifier,owner):
        with self.transaction() as session:
            job=require(session,DeploymentEvaluationJob,identifier)
            if job.state in TERMINAL: return job,False
            if job.state!="queued": raise ConflictError("Evaluation is already running; inspect its saved job")
            record=require(session,StrategyDeploymentRecord,job.deployment_id)
            if record.state!="paper_active" or record.active_terms_id!=job.terms_id or record.revision!=job.request["expected_revision"]:
                job.state="conflict";job.finished_at=now_utc();job.result={"evaluation":None,"message":"Queued funding/revision changed; no evaluation was started"}
                session.add(job);return job,False
            now=now_utc();job.state="running";job.owner=owner;job.started_at=now
            job.deadline=now+timedelta(seconds=RUNTIME_SECONDS);job.lease_until=now+timedelta(seconds=LEASE_SECONDS)
            session.add(job)
        return job,True

    def heartbeat(self,identifier,owner):
        with self.transaction() as session:
            job=live_job(session,identifier,owner)
            job.lease_until=min(job.deadline,now_utc()+timedelta(seconds=LEASE_SECONDS));session.add(job)

    def finish(self,identifier,owner,result,*,state="completed"):
        from fastapi.encoders import jsonable_encoder
        if state not in {"completed","failed","conflict"}: raise ValueError("Invalid terminal evaluation result")
        with self.transaction() as session:
            job=live_job(session,identifier,owner)
            job.state=state;job.result=jsonable_encoder(result);job.finished_at=now_utc();session.add(job)
        return job

    def recover_expired(self, *, stopped_cycle_id=None):
        # A supervisor may fence its own claims after confirming its cycle
        # process has terminated. It must never interrupt another live worker.
        if stopped_cycle_id is not None and (not stopped_cycle_id.startswith("dcycle_") or len(stopped_cycle_id) != 39):
            raise ValueError("Invalid stopped cycle identity")
        recovered=[]
        with self.transaction() as session:
            now=now_utc()
            for job in session.exec(select(DeploymentEvaluationJob).where(DeploymentEvaluationJob.state=="running")):
                stopped = bool(stopped_cycle_id and job.owner and job.owner.startswith(stopped_cycle_id+":"))
                if not stopped and job.lease_until and job.deadline and now<min(job.lease_until,job.deadline): continue
                record=require(session,StrategyDeploymentRecord,job.deployment_id)
                affected=record.state=="paper_active" and record.active_terms_id==job.terms_id and record.revision==job.request["expected_revision"]
                if affected:
                    record.state="paused";record.revision+=1;record.updated_at=now;session.add(record)
                job.state="interrupted";job.finished_at=now
                job.result={"evaluation":None,"failure":{"stage":"cycle_termination" if stopped else "lease_recovery","error_type":"InterruptedEvaluation"},
                    "message":"Evaluation interrupted. Any saved proposals remain evidence; entries require a fresh review. No order was approved or resubmitted.",
                    "entries_paused":affected,"cancellation_review_required":record.state=="paused"}
                session.add(job)
                self._event(session,record,"evaluation_interrupted","deployment-supervisor","Stopped cycle recovered" if stopped else "Expired evaluation lease recovered",
                    {"job_id":job.job_id,"entries_paused":affected,"capital_retained":record.active_terms_id is not None})
                recovered.append(job)
        return recovered

    def cancel(self,identifier,job_id,action):
        with self.transaction() as session:
            record=require(session,StrategyDeploymentRecord,identifier);self._revision(record,action)
            job=require(session,DeploymentEvaluationJob,job_id)
            if job.deployment_id!=identifier: raise ConflictError("Evaluation job belongs to another deployment")
            if job.state in TERMINAL: return job
            if job.state=="running" and record.state=="paper_active":
                record.state="paused";record.revision+=1;record.updated_at=now_utc();session.add(record)
            job.state="canceled";job.finished_at=now_utc();job.result={"evaluation":None,"message":"Evaluation canceled by the operator; no automatic retry"}
            session.add(job)
            self._event(session,record,"evaluation_canceled",action.actor,action.reason,{"job_id":job_id})
        return job


def execute_job(jobs,identifier,broker_resolver,store,*,cycle_id=None):
    """One fenced evaluation. Interrupted/terminal jobs are never retried."""
    owner=(cycle_id+":" if cycle_id else "")+uuid4().hex
    job,claimed=jobs.claim(identifier,owner)
    if not claimed: return job.result
    request=DeploymentEvaluationInput.model_validate(job.request)
    stop=Event()
    def pulse():
        while not stop.wait(5):
            try: jobs.heartbeat(identifier,owner)
            except Exception: return  # The final publication fence stays authoritative.
    thread=Thread(target=pulse,name="deployment-evaluation-lease",daemon=True);thread.start()
    try:
        from tradingagents.research.deployment_service import DeploymentService
        try: service=DeploymentService(jobs.sessions,broker_resolver())
        except Exception as exc:
            record=jobs.evaluation_failed(job.deployment_id,request,"broker_construction",type(exc).__name__,job_fence=(identifier,owner))
            result={"evaluation":None,"deployment":record,"failure":{"stage":"broker_construction","error_type":type(exc).__name__},
                "cancellations":[{"state":"cancellation_unavailable"}],"message":"Evaluation failed during broker setup; inspect saved state and entry cancellations before a fresh review."}
        else:
            result=service.evaluate(job.deployment_id,request,store,job_fence=(identifier,owner))
        return jobs.finish(identifier,owner,result,state="failed" if result.get("failure") else "completed").result
    except ConflictError as exc:
        try: jobs.finish(identifier,owner,{"evaluation":None,"message":str(exc)},state="conflict")
        except ConflictError: jobs.recover_expired()
        raise
    finally:
        stop.set();thread.join(timeout=1)


def install_job_guards(engine):
    with engine.begin() as connection:
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS deployment_one_pending_job ON research_deployment_jobs(deployment_id) WHERE state IN ('queued','running')"))
        fields=("job_id","deployment_id","terms_id","account_key","request_hash","request","created_at")
        condition=" OR ".join(f'OLD."{f}" IS NOT NEW."{f}"' for f in fields)
        connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS deployment_job_identity BEFORE UPDATE ON research_deployment_jobs WHEN {condition} BEGIN SELECT RAISE(ABORT,'evaluation request is immutable'); END"))
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS deployment_job_claim_pin BEFORE UPDATE ON research_deployment_jobs WHEN OLD.state!='queued' AND (OLD.owner IS NOT NEW.owner OR OLD.started_at IS NOT NEW.started_at OR OLD.deadline IS NOT NEW.deadline) BEGIN SELECT RAISE(ABORT,'evaluation claim is immutable'); END"))
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS deployment_job_terminal BEFORE UPDATE ON research_deployment_jobs WHEN OLD.state IN ('completed','failed','conflict','interrupted','canceled') BEGIN SELECT RAISE(ABORT,'evaluation result is immutable'); END"))
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS deployment_job_no_delete BEFORE DELETE ON research_deployment_jobs BEGIN SELECT RAISE(ABORT,'evaluation history is immutable'); END"))
