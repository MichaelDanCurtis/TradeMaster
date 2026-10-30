"""Research can request review; only the execution room manages paper authority."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
import requests
import os
from pathlib import Path

from tradingagents.research.deployment_contracts import DeploymentInput, DeploymentAction, DeploymentApproval, CapitalRevision, DeploymentReviewDecision, DeploymentEvaluationInput, DeploymentTargetInput
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.deployment_repository import DeploymentRepository
from tradingagents.research.deployment_service import DeploymentService
from tradingagents.research.repository import ConflictError, MissingRecordError
from tradingagents.ui.room_policy import enforce_room_tool


def create_deployment_router(sessions,broker_resolver):
    router=APIRouter(prefix="/api/research/deployments",tags=["paper-deployments"])
    repo=DeploymentRepository(sessions)
    from tradingagents.research.deployment_jobs import DeploymentJobs,execute_job
    jobs=DeploymentJobs(sessions)
    database=sessions.kw["bind"].url.database
    default_root=Path(database).resolve().parent/".research-artifacts" if database and database!=":memory:" else Path.cwd()/".research-artifacts"
    store=ArtifactStore(os.environ.get("TRADEMASTER_RESEARCH_ARTIFACTS",str(default_root)))
    def grant(permission):
        def dependency(x_trademaster_room: str=Header(default="research")):
            try: enforce_room_tool(x_trademaster_room,permission)
            except PermissionError as exc: raise HTTPException(status_code=403,detail=str(exc)) from exc
        return dependency
    def call(operation,*args,**kwargs):
        try: return operation(*args,**kwargs)
        except MissingRecordError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
        except ConflictError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
        except PermissionError as exc: raise HTTPException(status_code=403,detail=str(exc)) from exc
        except requests.RequestException as exc: raise HTTPException(status_code=503,detail="Paper provider observation is unavailable; no new order was submitted") from exc
    def service(): return DeploymentService(sessions,broker_resolver())
    read=[Depends(grant("deployment-read"))]
    request=[Depends(grant("deployment-request"))]
    manage=[Depends(grant("deployment-manage"))]

    @router.get("",dependencies=read)
    def listing(): return {"deployments":repo.list()}

    @router.get("/candidates",dependencies=read)
    def candidates(): return {"candidates":repo.candidates()}

    @router.get("/observations",dependencies=read)
    def observations(): return {"snapshots":[s for s in repo.list_snapshots() if s.evidence_kind=="prospective"]}

    @router.get("/runtime",dependencies=read)
    def runtime(account_key:str|None=None):
        from tradingagents.research.deployment_health import DeploymentHealth
        return call(DeploymentHealth(sessions).runtime,account_key)

    @router.get("/account",dependencies=manage)
    def account():
        def observe():
            snapshot=broker_resolver().paper_snapshot()
            return {"provider_id":snapshot.provider_id,"account_id":snapshot.account_id,"environment":snapshot.environment,"evidence_kind":snapshot.evidence_kind}
        return call(observe)

    @router.post("",dependencies=request,status_code=201)
    def create(payload:DeploymentInput): return call(repo.create,payload)

    @router.get("/{identifier}",dependencies=read)
    def detail(identifier:str): return call(repo.detail,identifier)

    @router.get("/{identifier}/execution-attribution",dependencies=read)
    def attribution(identifier:str,before:str|None=None,limit:int=Query(default=10,ge=1,le=25)):
        from tradingagents.research.execution_attribution import execution_attribution
        return call(execution_attribution,sessions,identifier,before=before,limit=limit)

    @router.post("/{identifier}/review",dependencies=manage)
    def review(identifier:str,payload:DeploymentAction): return call(lambda:service().review(identifier,payload))

    @router.post("/{identifier}/decision",dependencies=manage)
    def decision(identifier:str,payload:DeploymentReviewDecision): return call(repo.review_decision,identifier,payload)

    @router.post("/{identifier}/activate",dependencies=manage)
    def activate(identifier:str,payload:DeploymentApproval): return call(lambda:service().activate(identifier,payload))

    @router.post("/{identifier}/pause",dependencies=manage)
    def pause(identifier:str,payload:DeploymentAction):
        def perform():
            record=repo.pause(identifier,payload)
            try: return service().cancel_entries(record,payload.actor)
            except Exception as exc:
                return {"deployment":record,"cancellations":[{"state":"cancellation_unavailable","error_type":type(exc).__name__}],
                    "message":"Deployment is paused. Broker configuration or transport prevented cancellation; review outstanding entries and protection."}
        return call(perform)

    @router.post("/{identifier}/resume",dependencies=manage)
    def resume(identifier:str,payload:DeploymentApproval): return call(lambda:service().activate(identifier,payload,resume=True))

    @router.post("/{identifier}/capital",dependencies=manage)
    def capital(identifier:str,payload:CapitalRevision): return call(repo.change_capital,identifier,payload)

    @router.post("/{identifier}/retire",dependencies=manage)
    def retire(identifier:str,payload:DeploymentAction): return call(lambda:service().retire(identifier,payload))

    @router.post("/{identifier}/evaluate",dependencies=manage)
    def evaluate(identifier:str,payload:DeploymentEvaluationInput):
        def perform():
            job=jobs.enqueue(identifier,payload)
            return execute_job(jobs,job.job_id,broker_resolver,store)
        return call(perform)

    @router.post("/{identifier}/evaluation-jobs",dependencies=manage,status_code=202)
    def enqueue(identifier:str,payload:DeploymentEvaluationInput):
        job=call(jobs.enqueue,identifier,payload)
        message="Evaluation queued. A deployment worker must be running; no order is approved or submitted." if job.state=="queued" else f"This exact request already has a saved {job.state} job. No duplicate evaluation was queued."
        return {"job":job,"message":message}

    @router.post("/{identifier}/evaluation-jobs/{job_id}/cancel",dependencies=manage)
    def cancel_job(identifier:str,job_id:str,payload:DeploymentAction):
        def perform():
            job=jobs.cancel(identifier,job_id,payload)
            record=repo.detail(identifier)["deployment"]
            if record.state!="paused": return {"job":job,"message":"Queued evaluation canceled"}
            try: return {"job":job,**service().cancel_entries(record,payload.actor)}
            except Exception: return {"job":job,"message":"Evaluation canceled and entries paused. Broker cancellation is unavailable; inspect outstanding entries."}
        return call(perform)

    @router.post("/{identifier}/targets",dependencies=manage)
    def prepare(identifier:str,payload:DeploymentTargetInput): return call(lambda:service().prepare(identifier,payload))
    return router
