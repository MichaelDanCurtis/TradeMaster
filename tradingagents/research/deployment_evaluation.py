"""Immutable prospective evaluations and symbol programs; no broker submission."""
import hashlib
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

from sqlalchemy import text
from sqlmodel import select

from tradingagents.research.contracts import SnapshotManifest, StrategySpec, GuidanceRules, content_hash
from tradingagents.research.deployment_contracts import DeploymentTerms
from tradingagents.research.deployment_models import (StrategyDeploymentRecord, DeploymentTermsRecord,
    DeploymentEvaluationRecord, DeploymentProgramLink, DeploymentOrderTargetRecord)
from tradingagents.research.deployment_repository import DeploymentRepository, observed_account
from tradingagents.research.models import DatasetSnapshotRecord, StrategyVersionRecord
from tradingagents.research.execution_contracts import ExactPaperOrder
from tradingagents.research.execution_repository import PaperExecutionRepository
from tradingagents.research.repository import ConflictError, require
from tradingagents.research.strategies.deployment_portfolio import deployment_portfolio
from tradingagents.ui.models import ExecutionProgramRecord, ExecutionProgramEventRecord, RunRecord, now_utc


_BUILD = content_hash({name:hashlib.sha256(Path(__file__).parent.joinpath(name).read_bytes()).hexdigest()
    for name in ("deployment_evaluation.py", "strategies/deployment_portfolio.py", "strategies/trend.py",
                 "strategies/portfolio_risk.py", "strategies/guidance_deployment.py", "strategies/guidance_portfolio.py",
                 "strategies/guidance_quality.py", "deployment_guidance_state.py", "deployment_repository.py",
                 "deployment_jobs.py", "deployment_process.py", "deployment_child.py", "strategies/deployment_risk.py", "evidence/validation.py", "evidence/extraction.py", "data/contracts.py", "contracts.py")})


class DeploymentEvaluator(DeploymentRepository):
    def evaluate(self, identifier, request, reconciliation_id, store, *, job_fence=None):
        # Artifact parsing is outside the writer transaction. Its content address
        # and the immutable database snapshot are checked again before saving.
        with self.sessions() as session:
            source=require(session,DatasetSnapshotRecord,request.snapshot_id)
            manifest=SnapshotManifest.model_validate(source.payload)
            if content_hash(manifest)!=source.content_hash:
                raise ConflictError("Prospective snapshot manifest failed its integrity check")
        if manifest.evidence_kind!="prospective" or manifest.availability!="recorded_receipt":
            raise ConflictError("Deployment evaluation requires a prospective snapshot with recorded receipt times")
        dataset=store.dataset(manifest)
        # Release the read snapshot before CPU work so pause/cancel and lease
        # heartbeats are never held behind a calculation writer lock.
        with self.sessions() as session:
            session.execute(text("BEGIN"))
            if job_fence:
                from tradingagents.research.deployment_jobs import live_job
                live_job(session,*job_fence)
            record=require(session,StrategyDeploymentRecord,identifier)
            if not record.active_terms_id:
                raise ConflictError("Deployment has no approved capital envelope")
            digest=content_hash({"deployment_id":identifier,"terms_id":record.active_terms_id,
                                 "snapshot_hash":source.content_hash,"as_of":request.as_of.astimezone(timezone.utc).isoformat()})
            previous=session.exec(select(DeploymentEvaluationRecord).where(DeploymentEvaluationRecord.request_hash==digest)).first()
            if previous:
                return previous
            self._revision(record,request)
            if record.state!="paper_active":
                raise ConflictError("Only an active reviewed deployment can evaluate new targets")
            terms=DeploymentTerms.model_validate(require(session,DeploymentTermsRecord,record.active_terms_id).payload)
            receipt,snapshot=observed_account(session,reconciliation_id,record.account_key,terms.execution_policy)
            if snapshot.evidence_kind!="broker_paper":
                raise ConflictError("A fixture account cannot create prospective deployment targets")
            version=require(session,StrategyVersionRecord,record.version_id)
            if content_hash(version.payload)!=version.content_hash:
                raise ConflictError("Frozen strategy version failed its integrity check")
            spec=StrategySpec.model_validate(version.payload["spec"])
            owner=f"deployment:{identifier}"
            by_symbol={p["symbol"]:p for p in receipt.report["positions"]}
            quantities={i.instrument_id:D(by_symbol.get(i.symbol,{}).get("owners",{}).get(owner,"0")) for i in spec.universe}
            now=now_utc()
            if request.as_of>now:
                raise ConflictError("A prospective decision cannot use a future information cutoff")
            latest=session.exec(select(DeploymentEvaluationRecord).where(DeploymentEvaluationRecord.deployment_id==identifier)
                .order_by(DeploymentEvaluationRecord.created_at.desc(),DeploymentEvaluationRecord.evaluation_id.desc())).first()
            if latest and latest.payload.get("as_of") and request.as_of<datetime.fromisoformat(latest.payload["as_of"]):
                raise ConflictError("Prospective evaluation cannot move the information cutoff backwards")
            guidance_context=None;source_hashes={};state_error=None
            if isinstance(spec.rules,GuidanceRules):
                from tradingagents.research.deployment_guidance_state import restore_guidance_context
                try:
                    guidance_context,source_hashes=restore_guidance_context(session,record,spec,receipt,snapshot,dataset,request.as_of)
                except ValueError as exc:
                    state_error=str(exc)
        result=deployment_portfolio(dataset,spec,request.as_of,terms.capital_usd,quantities,guidance_context=guidance_context)
        if state_error:
            result.update(status="unavailable",reason=state_error,portfolio=[])
        if isinstance(spec.rules,GuidanceRules): result["guidance_source_hashes"]=source_hashes
        if result["execution_deadline"] and now>=datetime.fromisoformat(result["execution_deadline"]):
            raise ConflictError("This decision's next-session execution window has passed")
        # Ambiguous ownership is saved as an explicit unavailable evaluation,
        # not treated as zero exposure or reassigned to this deployment.
        if any(D(q)>0 and name!=owner for i in spec.universe for name,q in by_symbol.get(i.symbol,{}).get("owners",{}).items()):
            result.update(status="unavailable",reason="A strategy symbol has shared/manual ownership; explicit allocation is required",portfolio=[])
        from tradingagents.research.strategies.deployment_risk import funded_portfolio_risk
        result["funded_risk"]={"observed":funded_portfolio_risk(dataset,spec,request.as_of,terms.capital_usd,quantities,
            basis="reconciled_holdings_at_decision_prices",policy=terms.execution_policy),"proposed":None}
        if result["status"]=="targets":
            proposed={row["instrument_id"]:D(row["desired_quantity"]) for row in result["portfolio"]}
            result["funded_risk"]["proposed"]=funded_portfolio_risk(dataset,spec,request.as_of,terms.capital_usd,proposed,
                basis="proposed_whole_shares",policy=terms.execution_policy)
        with self.transaction() as session:
            if job_fence:
                live_job(session,*job_fence)
            current=require(session,StrategyDeploymentRecord,identifier)
            self._revision(current,request)
            if current.state!="paper_active" or current.active_terms_id!=record.active_terms_id or current.version_id!=record.version_id:
                raise ConflictError("Deployment changed while calculating; no proposal was published")
            observed_account(session,reconciliation_id,current.account_key,terms.execution_policy)
            newest=session.exec(select(DeploymentEvaluationRecord).where(DeploymentEvaluationRecord.deployment_id==identifier)
                .order_by(DeploymentEvaluationRecord.created_at.desc(),DeploymentEvaluationRecord.evaluation_id.desc())).first()
            if (newest.evaluation_id if newest else None)!=(latest.evaluation_id if latest else None):
                raise ConflictError("A newer evaluation arrived during calculation; inspect it before retrying")
            if isinstance(spec.rules,GuidanceRules):
                try:
                    fresh_context,fresh_hashes=restore_guidance_context(session,current,spec,receipt,snapshot,dataset,request.as_of)
                    fresh_error=None
                except ValueError as exc:
                    fresh_context=None;fresh_hashes={};fresh_error=str(exc)
                if (fresh_context,fresh_hashes,fresh_error)!=(guidance_context,source_hashes,state_error):
                    raise ConflictError("Guidance execution history changed during calculation")
            record=current
            now=now_utc()
            if result["execution_deadline"] and now>=datetime.fromisoformat(result["execution_deadline"]):
                raise ConflictError("This decision's next-session execution window has passed")
            payload={**result,"schema_version":1,"version_id":record.version_id,"version_hash":version.content_hash,
                     "evaluation_job_id":job_fence[0] if job_fence else None,
                     "snapshot_id":source.snapshot_id,"snapshot_hash":source.content_hash,
                     "evidence_kind":manifest.evidence_kind,"provenance":manifest.provenance,
                     "data_limitations":manifest.limitations,"provenance_verification":"provider declarations; independent entitlement verification is not established",
                     "terms_id":record.active_terms_id,"reconciliation_id":receipt.reconciliation_id,
                     "account_observed_at":snapshot.observed_at.isoformat(),"evaluated_at":now.isoformat(),
                     "build_hash":_BUILD,"actor":request.actor,"reason_for_evaluation":request.reason}
            evaluation=DeploymentEvaluationRecord(deployment_id=identifier,terms_id=record.active_terms_id,
                request_hash=digest,payload=payload)
            if job_fence:
                live_job(session,*job_fence)
            session.add(evaluation);session.flush()
            if result["status"]=="targets":
                for row in result["portfolio"]:
                    if not row["delta_quantity"]: continue
                    program=ExecutionProgramRecord(symbol=row["symbol"],algorithm="strategy_target",
                        state="preview_ready",mode="paper",approval_status="required",live_submission_enabled=False,
                        trigger_points=[{"type":"next_session_open","at":result["execution_opens_at"]}],
                        circuit_breakers=[{"type":"human_order_approval"},{"type":"fresh_account_and_funding"},{"type":"sells_before_buys"}],
                        payload={"deployment_id":identifier,"evaluation_id":evaluation.evaluation_id,
                                 "version_id":record.version_id,"terms_id":record.active_terms_id,"target":row,
                                 "status":"theoretical_target","order_authority":False})
                    session.add(program);session.flush()
                    session.add(DeploymentProgramLink(deployment_id=identifier,program_id=program.program_id))
                    session.add(ExecutionProgramEventRecord(program_id=program.program_id,event_type="strategy_target_proposed",
                        summary="Frozen theoretical portfolio target; no exact order or approval yet",payload=program.payload))
            if result["status"]=="unavailable":
                record.state="paused";record.revision+=1;record.updated_at=now
                session.add(record)
            self._event(session,record,"portfolio_evaluated",request.actor,request.reason,
                        {"evaluation_id":evaluation.evaluation_id,"status":result["status"],"reason":result["reason"]})
            if job_fence:
                live_job(session,*job_fence)
        return evaluation

    def prepare(self, identifier, request, reconciliation_id):
        """Freeze one delta and an operator-specified limit; never approve or POST."""
        with self.transaction() as session:
            record=require(session,StrategyDeploymentRecord,identifier)
            self._revision(record,request)
            evaluation=require(session,DeploymentEvaluationRecord,request.evaluation_id)
            if evaluation.deployment_id!=identifier or evaluation.terms_id!=record.active_terms_id:
                raise ConflictError("Evaluation does not belong to the active deployment funding")
            row=next((r for r in evaluation.payload.get("portfolio",[]) if r["instrument_id"]==request.instrument_id),None)
            if evaluation.payload.get("status")!="targets" or not row or not row["delta_quantity"]:
                raise ConflictError("Evaluation has no changed target for this instrument")
            terms=DeploymentTerms.model_validate(require(session,DeploymentTermsRecord,record.active_terms_id).payload)
            _,snapshot=observed_account(session,reconciliation_id,record.account_key,terms.execution_policy,
                                        new_risk=row["delta_quantity"]>0)
            target_id="dtgt_"+content_hash({"evaluation_id":evaluation.evaluation_id,"instrument_id":request.instrument_id})
            run_id="run_"+target_id.removeprefix("dtgt_")
            exact=ExactPaperOrder(symbol=row["symbol"],side="buy" if row["delta_quantity"]>0 else "sell",
                quantity=abs(row["delta_quantity"]),limit_price_usd=request.limit_price_usd,
                risk_group=row["risk_group"],fee_reserve_usd=terms.fee_reserve_per_order_usd,
                expires_at=datetime.fromisoformat(evaluation.payload["execution_deadline"]))
            existing=session.get(DeploymentOrderTargetRecord,target_id)
            if existing:
                if existing.order!=exact.model_dump(mode="json"):
                    raise ConflictError("This evaluated target already has frozen order terms; it cannot be repriced or resized")
            else:
                # Guard before writing an immutable target as well as at preview
                # and claim. Changes between transactions are checked again.
                check_evaluation_target(session,record,evaluation,row,snapshot)
                target=DeploymentOrderTargetRecord(target_id=target_id,evaluation_id=evaluation.evaluation_id,
                    deployment_id=identifier,terms_id=record.active_terms_id,content_hash=content_hash(exact),order=exact.model_dump(mode="json"))
                session.add(target)
                session.add(RunRecord(run_id=run_id,ticker=row["symbol"],trade_date=snapshot.observed_at.date().isoformat(),
                    status="completed",config={"broker_mode":"paper","source":"deployment_target",
                                               "deployment_id":identifier,"evaluation_id":evaluation.evaluation_id}))
                self._event(session,record,"exact_target_prepared",request.actor,request.reason,
                            {"evaluation_id":evaluation.evaluation_id,"target_id":target_id,"exact_order":exact.model_dump(mode="json")})
        return PaperExecutionRepository(self.sessions).preview(None,exact,terms.execution_policy,snapshot,
            deployment_id=identifier,target_id=target_id,run_id=run_id,
            budget=exact.maximum_notional_usd+exact.fee_reserve_usd,
            intent_payload={"source":"deployment_target","deployment_id":identifier,
                            "evaluation_id":evaluation.evaluation_id,"target_id":target_id,
                            "theoretical_target":row})


def check_evaluation_target(session, record, evaluation, row, snapshot, *, target_id=None):
    """Recheck original holdings and serial sale completion at the order boundary."""
    from tradingagents.research.accounting_models import PaperReconciliationRecord
    from tradingagents.research.execution_models import ExactPaperOrderRecord
    from tradingagents.research.execution_contracts import TERMINAL
    payload=evaluation.payload
    if not record.active_terms_id or record.state in {"draft","retired"} or (row["delta_quantity"]>0 and record.state!="paper_active"):
        raise ConflictError("Deployment is paused or not funded for this target")
    if payload.get("schema_version")!=1 or payload.get("status")!="targets":
        raise ConflictError("Exact deployment orders require a supported saved portfolio evaluation")
    latest=session.exec(select(DeploymentEvaluationRecord).where(DeploymentEvaluationRecord.deployment_id==record.deployment_id)
        .order_by(DeploymentEvaluationRecord.created_at.desc(),DeploymentEvaluationRecord.evaluation_id.desc())).first()
    if latest.evaluation_id!=evaluation.evaluation_id:
        raise ConflictError("A newer portfolio evaluation supersedes this target")
    now=now_utc()
    if not datetime.fromisoformat(payload["execution_opens_at"])<=now<datetime.fromisoformat(payload["execution_deadline"]):
        raise ConflictError("Exact targets are executable only in their saved next-session opening window")
    receipt=session.exec(select(PaperReconciliationRecord).where(PaperReconciliationRecord.account_key==record.account_key)
        .order_by(PaperReconciliationRecord.created_at.desc())).first()
    if receipt is None or not receipt.report["reconciled"]:
        raise ConflictError("Target needs reconciled actual holdings")
    owner=f"deployment:{record.deployment_id}"
    quantities={p["symbol"]:D(p["owners"].get(owner,"0")) for p in receipt.report["positions"]}
    if quantities.get(row["symbol"],D(0))!=D(row["current_quantity"]):
        raise ConflictError("Actual holdings changed since this target was evaluated; a new evaluation is required")
    if any(o.symbol==row["symbol"] for o in snapshot.open_orders):
        raise ConflictError("An outstanding symbol order must settle before preparing another strategy delta")
    if row["delta_quantity"]>0:
        sells=[r for r in payload["portfolio"] if r["delta_quantity"]<0]
        sell_symbols={r["symbol"] for r in sells}
        if any(quantities.get(r["symbol"],D(0))!=D(r["desired_quantity"]) for r in sells) or any(o.symbol in sell_symbols for o in snapshot.open_orders):
            raise ConflictError("Planned reductions must be filled and reconciled before any portfolio buy")
    target_id=target_id or "dtgt_"+content_hash({"evaluation_id":evaluation.evaluation_id,"instrument_id":row["instrument_id"]})
    for order in session.exec(select(ExactPaperOrderRecord).where(ExactPaperOrderRecord.deployment_id==record.deployment_id)):
        if order.target_id==target_id or order.state in TERMINAL or order.order["symbol"]!=row["symbol"]: continue
        if order.state in {"previewed","approved"} and datetime.fromisoformat(order.order["expires_at"])<=now: continue
        raise ConflictError("Another exact target for this symbol is still outstanding")
