"""Human-reviewed paper observation baselines and read-only broker reconciliation."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import Field
import requests

from tradingagents.research.accounting_repository import PaperAccountingRepository
from tradingagents.research.accounting_service import reconcile_paper_account
from tradingagents.research.contracts import Contract, Digest, Identifier
from tradingagents.research.execution_repository import account_key
from tradingagents.research.repository import ConflictError, MissingRecordError
from tradingagents.ui.room_policy import enforce_room_tool


class BaselineApproval(Contract):
    expected_hash: Digest
    actor: Identifier


class CorrectionApproval(Contract):
    expected_hash: Digest
    actor: Identifier
    reason: str = Field(min_length=1,max_length=2000)


def create_accounting_router(session_factory, broker_resolver):
    router = APIRouter(prefix="/api/paper-accounting", tags=["paper-accounting"])
    repo = PaperAccountingRepository(session_factory)
    def grant(permission):
        def dependency(x_trademaster_room: str = Header(default="transactions")):
            try: enforce_room_tool(x_trademaster_room, permission)
            except PermissionError as exc: raise HTTPException(status_code=403,detail=str(exc)) from exc
        return dependency
    def call(operation, *args):
        try: return operation(*args)
        except MissingRecordError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
        except ConflictError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
        except PermissionError as exc: raise HTTPException(status_code=403,detail=str(exc)) from exc
        except requests.RequestException as exc: raise HTTPException(status_code=503,detail="Broker account observation is unavailable; no order was submitted") from exc
    @router.get("/accounts",dependencies=[Depends(grant("account-read"))])
    def accounts(): return {"accounts":repo.list_accounts()}

    @router.post("/baselines/preview",dependencies=[Depends(grant("paper-account-review"))])
    def preview():
        def prepare(): return repo.preview_baseline(broker_resolver().paper_snapshot())
        return call(prepare)

    @router.post("/baselines/{baseline_id}/approve",dependencies=[Depends(grant("paper-account-review"))])
    def approve(baseline_id: str, request: BaselineApproval):
        def perform():
            from tradingagents.research.accounting_models import PaperBaselineRecord
            from tradingagents.research.repository import require
            with repo.sessions() as session: baseline=require(session,PaperBaselineRecord,baseline_id)
            broker=broker_resolver()
            identity=broker.paper_identity() if callable(getattr(broker,"paper_identity",None)) else broker.paper_snapshot()
            if account_key(identity)!=baseline.account_key: raise ConflictError("Configured broker account changed since baseline preview")
            return repo.approve_baseline(baseline_id,request.expected_hash,request.actor)
        return call(perform)

    @router.get("/accounts/{key}/history",dependencies=[Depends(grant("account-read"))])
    def history(key: str): return {"reconciliations":call(repo.history,key)}

    @router.get("/accounts/{key}/corrections",dependencies=[Depends(grant("account-read"))])
    def corrections(key:str): return call(repo.corrections,key)

    @router.post("/accounts/{key}/corrections/preview",dependencies=[Depends(grant("paper-account-review"))])
    def preview_corrections(key:str): return call(repo.preview_corrections,key)

    @router.post("/accounts/{key}/corrections/{review_id}/approve",dependencies=[Depends(grant("paper-account-review"))])
    def approve_corrections(key:str,review_id:str,request:CorrectionApproval):
        return call(repo.approve_corrections,key,review_id,request.expected_hash,request.actor,request.reason)

    @router.get("/accounts/{key}/deployments",dependencies=[Depends(grant("account-read"))])
    def deployments(key:str):
        from sqlmodel import select
        from tradingagents.research.deployment_models import StrategyDeploymentRecord
        with repo.sessions() as session:
            rows=session.exec(select(StrategyDeploymentRecord).where(StrategyDeploymentRecord.account_key==key)
                .order_by(StrategyDeploymentRecord.created_at.desc())).all()
            return {"deployments":[{"deployment_id":r.deployment_id,"name":r.name,"state":r.state,"version_id":r.version_id} for r in rows]}

    @router.get("/accounts/{key}/deployment-performance",dependencies=[Depends(grant("account-read"))])
    def deployment_performance(key:str):
        from tradingagents.research.deployment_performance import account_deployment_performance
        return call(account_deployment_performance,repo.sessions,key)

    @router.get("/accounts/{key}/deployments/{identifier}/execution-attribution",dependencies=[Depends(grant("account-read"))])
    def attribution(key:str,identifier:str,before:str|None=None,limit:int=Query(default=10,ge=1,le=25)):
        def read():
            from tradingagents.research.deployment_models import StrategyDeploymentRecord
            from tradingagents.research.execution_attribution import execution_attribution
            from tradingagents.research.repository import require
            with repo.sessions() as session:
                if require(session,StrategyDeploymentRecord,identifier).account_key!=key:
                    raise ConflictError("Deployment belongs to a different account")
            return execution_attribution(repo.sessions,identifier,before=before,limit=limit)
        return call(read)

    @router.post("/accounts/{key}/reconcile",dependencies=[Depends(grant("paper-account-reconcile"))])
    def reconcile(key: str):
        def perform(): return reconcile_paper_account(broker_resolver(),repo,key)
        return call(perform)
    return router
