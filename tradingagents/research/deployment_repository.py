"""Paper promotion requires immutable evidence, fresh accounting and human review."""
from datetime import datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlmodel import select

from tradingagents.research.accounting_models import PaperReconciliationRecord
from tradingagents.research.contracts import ExperimentResult, SnapshotManifest, StrategySpec, GuidanceRules, content_hash
from tradingagents.research.deployment_contracts import DeploymentInput, DeploymentTerms, DeploymentAction, DeploymentApproval, CapitalRevision, FundingCapacity, DeploymentReviewDecision
from tradingagents.research.deployment_models import StrategyDeploymentRecord, DeploymentTermsRecord, PromotionReviewRecord, DeploymentEventRecord, DeploymentProgramLink, DeploymentOrderTargetRecord, DeploymentEvaluationRecord, DeploymentEvaluationJob
from tradingagents.research.evaluation.comparison import EvidenceReport
from tradingagents.research.execution_contracts import PaperAccountSnapshot, TERMINAL
from tradingagents.research.execution_models import ExactPaperOrderRecord, PaperExecutionAttemptRecord, PaperExecutionAccountRecord, PaperReservationRecord
from tradingagents.research.execution_repository import account_key, require_fresh
from tradingagents.research.models import StrategyRecord, StrategyVersionRecord, ExperimentRecord, DatasetSnapshotRecord, ResearchPlanRecord
from tradingagents.research.repository import ResearchRepository, ConflictError, require
from tradingagents.ui.models import ApprovalLedgerRecord, now_utc


def account_frame(snapshot):
    """Review material economics separately from the refresh timestamp."""
    return snapshot.model_dump(mode="json",exclude={"started_at","observed_at","limitations"})


def observed_account(session, reconciliation_id, key, policy, *, new_risk=True):
    receipt=require(session,PaperReconciliationRecord,reconciliation_id)
    if receipt.account_key!=key: raise ConflictError("Accounting receipt belongs to another account")
    latest=session.exec(select(PaperReconciliationRecord).where(PaperReconciliationRecord.account_key==key).order_by(PaperReconciliationRecord.created_at.desc())).first()
    if latest.reconciliation_id!=receipt.reconciliation_id:
        raise ConflictError("Refresh the latest account reconciliation before deployment review")
    if not receipt.report["reconciled"] or (new_risk and receipt.report["drawdown_fraction"] is None):
        raise ConflictError("Deployment needs reconciled account history and observed drawdown")
    snapshot=PaperAccountSnapshot.model_validate(receipt.request["snapshot"])
    snapshot.drawdown_fraction=D(receipt.report["drawdown_fraction"]) if receipt.report["drawdown_fraction"] is not None else None
    if new_risk:
        require_fresh(snapshot,policy)
    elif not snapshot.complete or snapshot.started_at<now_utc()-timedelta(seconds=policy.snapshot_max_age_seconds) or snapshot.observed_at>now_utc()+timedelta(seconds=1):
        raise ConflictError("Retirement requires a fresh complete account observation")
    account=session.get(PaperExecutionAccountRecord,key)
    if account and account.last_execution_at and snapshot.started_at<=account.last_execution_at:
        raise ConflictError("Account execution changed after reconciliation; refresh it")
    attempts=list(session.exec(select(PaperExecutionAttemptRecord).where(PaperExecutionAttemptRecord.account_key==key)))
    if any(a.state in {"unknown","dispatching"} for a in attempts):
        raise ConflictError("Unresolved submissions must be reconciled before deployment review")
    return receipt,snapshot


def funding_capacity(session, key, snapshot, report, proposed, deployment_id=None):
    """Allocate account equity once; pending sells never finance a new envelope."""
    active=list(session.exec(select(StrategyDeploymentRecord).where(StrategyDeploymentRecord.account_key==key).where(StrategyDeploymentRecord.active_terms_id.is_not(None)).where(StrategyDeploymentRecord.state!="retired")))
    budgets={row.deployment_id:D(require(session,DeploymentTermsRecord,row.active_terms_id).payload["capital_usd"]) for row in active}
    other=sum((value for owner,value in budgets.items() if owner!=deployment_id),D(0))
    marks={p.symbol:p.market_value_usd/p.quantity for p in snapshot.positions if p.quantity}
    own=unallocated=D(0)
    allocated_exposure={owner:D(0) for owner in budgets}
    for position in report["positions"]:
        for owner,quantity in position["owners"].items():
            value=D(quantity)*marks.get(position["symbol"],D(0))
            if owner==f"deployment:{deployment_id}": own+=value
            elif owner.removeprefix("deployment:") not in budgets: unallocated+=value
            else: allocated_exposure[owner.removeprefix("deployment:")]+=value
    exacts=list(session.exec(select(ExactPaperOrderRecord).where(ExactPaperOrderRecord.account_key==key)))
    by_client={order.intent_id:order.deployment_id for order in exacts}
    pending=[(o.client_order_id,o.remaining_quantity,o.maximum_price_usd,D(0)) for o in snapshot.open_orders if o.side=="buy"]
    remote={o.client_order_id for o in snapshot.open_orders}
    for reservation in session.exec(select(PaperReservationRecord).where(PaperReservationRecord.account_key==key).where(PaperReservationRecord.active==True)):
        if reservation.side!="buy": continue
        attempt=require(session,PaperExecutionAttemptRecord,reservation.attempt_id)
        if attempt.client_order_id not in remote:
            pending.append((attempt.client_order_id,D(reservation.quantity),D(reservation.price_usd),D(reservation.fee_usd)))
        else:
            pending.append((attempt.client_order_id,D(0),D(0),D(reservation.fee_usd)))
    own_pending=unallocated_pending=D(0)
    limitations=[]
    for client,quantity,price,fee in pending:
        if price is None and quantity:
            limitations.append("An unbounded pending buy prevents funding allocation")
            continue
        value=quantity*(price or D(0))+fee
        owner=by_client.get(client)
        if deployment_id is not None and owner==deployment_id: own_pending+=value
        elif owner not in budgets: unallocated_pending+=value
        else: allocated_exposure[owner]+=value
    # A price gap can leave another deployment above its envelope. Count that
    # residual exposure as well; the nominal envelope cannot hide it.
    other=sum((max(value,allocated_exposure[owner]) for owner,value in budgets.items() if owner!=deployment_id),D(0))
    if "owner_equity_history" in report:
        from tradingagents.research.deployment_performance import flows_for
        owner_points=report["owner_equity_history"][-1]["owners"]
        other=D(0)
        for identifier,value in budgets.items():
            if identifier==deployment_id: continue
            point=owner_points.get(f"deployment:{identifier}")
            pnl=D(point["equity_without_allocations_usd"]) if point and point["equity_without_allocations_usd"] is not None else D(0)
            book_equity=sum((D(flow.amount_usd) for flow in flows_for(session,identifier)),D(0))+pnl
            other+=max(value,allocated_exposure[identifier],book_equity)
    available=snapshot.equity_usd-other-unallocated-unallocated_pending
    return FundingCapacity(account_equity_usd=snapshot.equity_usd,other_envelopes_usd=other,
        unallocated_holdings_usd=unallocated,unallocated_pending_buys_usd=unallocated_pending,
        own_holdings_usd=own,own_pending_buys_usd=own_pending,proposed_envelope_usd=proposed,
        available_envelope_usd=available,allowed=not limitations and proposed<=available and own+own_pending<=proposed,
        limitations=limitations)


def check_deployment_order(session, deployment_id, target_id, snapshot, order, policy):
    """Called inside the same account claim transaction as cash reservations."""
    key=account_key(snapshot)
    active=session.exec(select(StrategyDeploymentRecord).where(StrategyDeploymentRecord.account_key==key).where(StrategyDeploymentRecord.active_terms_id.is_not(None)).where(StrategyDeploymentRecord.state!="retired")).first()
    if not deployment_id and (not active or order.side=="sell"): return
    latest=session.exec(select(PaperReconciliationRecord).where(PaperReconciliationRecord.account_key==key).order_by(PaperReconciliationRecord.created_at.desc())).first()
    if latest is None or not latest.report["reconciled"]:
        raise ConflictError("Allocated capital requires reconciled account ownership")
    if order.side=="buy" and (latest.report["drawdown_fraction"] is None or snapshot.drawdown_fraction!=D(latest.report["drawdown_fraction"])):
        raise ConflictError("Allocated capital requires the reconciled drawdown observation")
    observed=PaperAccountSnapshot.model_validate(latest.request["snapshot"])
    if observed.model_dump(exclude={"drawdown_fraction","limitations"})!=snapshot.model_dump(exclude={"drawdown_fraction","limitations"}):
        raise ConflictError("Funding ownership does not match this fresh account snapshot")
    if not deployment_id:
        capacity=funding_capacity(session,key,snapshot,latest.report,D(0))
        if not capacity.allowed or order.maximum_notional_usd+order.fee_reserve_usd>capacity.available_envelope_usd:
            raise ConflictError("Manual entry would spend capital allocated to a deployment")
        return
    record=require(session,StrategyDeploymentRecord,deployment_id)
    if record.account_key!=key or not record.active_terms_id or record.state in {"draft","retired"}:
        raise ConflictError("Deployment is not funded for this paper account")
    if order.side=="buy" and record.state!="paper_active":
        raise ConflictError("Deployment is paused or under review; new entries are blocked")
    if order.side=="buy" and session.exec(select(DeploymentEvaluationJob).where(DeploymentEvaluationJob.deployment_id==deployment_id)
        .where(DeploymentEvaluationJob.state.in_(["queued","running"]))).first():
        raise ConflictError("Pending evaluation must complete or be recovered before a new entry")
    if order.stop_loss_usd is not None or order.take_profit_usd is not None:
        raise ConflictError("The frozen strategy evaluator uses plain limit targets; protective children require a separate supported policy")
    target=require(session,DeploymentOrderTargetRecord,target_id or "")
    if target.deployment_id!=deployment_id or target.terms_id!=record.active_terms_id or content_hash(order)!=target.content_hash or target.order!=order.model_dump(mode="json"):
        raise ConflictError("Exact order differs from the frozen deployment target or funding revision")
    evaluation=require(session,DeploymentEvaluationRecord,target.evaluation_id)
    row=next((r for r in evaluation.payload.get("portfolio",[]) if r["symbol"]==order.symbol),None)
    if row is None or abs(row["delta_quantity"])!=order.quantity or (row["delta_quantity"]>0)!=(order.side=="buy"):
        raise ConflictError("Exact order differs from its evaluated portfolio delta")
    from tradingagents.research.deployment_evaluation import check_evaluation_target
    check_evaluation_target(session,record,evaluation,row,snapshot,target_id=target.target_id)
    terms=DeploymentTerms.model_validate(require(session,DeploymentTermsRecord,record.active_terms_id).payload)
    if terms.execution_policy!=policy or order.fee_reserve_usd!=terms.fee_reserve_per_order_usd:
        raise ConflictError("Order execution policy differs from the reviewed deployment terms")
    spec=StrategySpec.model_validate(require(session,StrategyVersionRecord,record.version_id).payload["spec"])
    instruments={i.symbol:i for i in spec.universe}
    if order.symbol not in instruments or order.risk_group!=instruments[order.symbol].risk_group:
        raise ConflictError("Order is outside the frozen universe or risk classification")
    position=next((p for p in latest.report["positions"] if p["symbol"]==order.symbol),None)
    owner=f"deployment:{deployment_id}"
    if position and any(D(quantity)>0 and name!=owner for name,quantity in position["owners"].items()):
        raise ConflictError("This symbol has shared/manual ownership; resolve allocation before strategy trading")
    if order.side=="sell":
        if D(order.quantity)>D(position["owners"].get(owner,"0") if position else "0"):
            raise ConflictError("Deployment reduction exceeds its attributed shares")
        return
    capacity=funding_capacity(session,key,snapshot,latest.report,terms.capital_usd,deployment_id)
    cost=order.maximum_notional_usd+order.fee_reserve_usd
    from tradingagents.research.deployment_performance import allocation_state
    book=allocation_state(session,record,latest)
    if cost+capacity.own_pending_buys_usd+terms.capital_usd*policy.cash_reserve_fraction>D(book["cash_usd"]):
        raise ConflictError("Entry exceeds attributed deployment cash after pending orders and reserve")
    if not capacity.allowed or capacity.own_holdings_usd+capacity.own_pending_buys_usd+cost>terms.capital_usd*(1-policy.cash_reserve_fraction):
        raise ConflictError("Entry exceeds the deployment's funded capital or cash reserve")
    # Include all pending account buys against this strategy's symbol/group
    # limits. Unknown classification remains conservative.
    positions={p.symbol:p for p in snapshot.positions}
    pending=[(o.symbol,o.remaining_quantity*(o.maximum_price_usd or D(0))) for o in snapshot.open_orders if o.side=="buy"]
    remote={o.client_order_id for o in snapshot.open_orders}
    for reservation in session.exec(select(PaperReservationRecord).where(PaperReservationRecord.account_key==key).where(PaperReservationRecord.active==True)):
        attempt=require(session,PaperExecutionAttemptRecord,reservation.attempt_id)
        if reservation.side=="buy" and attempt.client_order_id not in remote:
            pending.append((reservation.symbol,D(reservation.quantity)*D(reservation.price_usd)))
    symbol_value=(positions[order.symbol].market_value_usd if order.symbol in positions else D(0))+sum((v for s,v in pending if s==order.symbol),D(0))
    if symbol_value+order.maximum_notional_usd>terms.capital_usd*policy.max_position_fraction:
        raise ConflictError("Entry exceeds deployment position concentration")
    group_symbols={i.symbol for i in spec.universe if i.risk_group==order.risk_group}
    group_value=sum((p.market_value_usd for p in snapshot.positions if p.symbol in group_symbols),D(0))+sum((v for s,v in pending if s in group_symbols),D(0))
    if group_value+order.maximum_notional_usd>terms.capital_usd*policy.max_group_fraction:
        raise ConflictError("Entry exceeds deployment risk-group concentration")
    market_day=snapshot.observed_at.astimezone(ZoneInfo("America/New_York")).date()
    turnover=sum((D(fill["quantity"])*D(fill["price_usd"]) for fill in latest.report["fills"]
        if fill["executor"]==owner and datetime.fromisoformat(fill["effective_at"]).astimezone(ZoneInfo("America/New_York")).date()==market_day),D(0))
    deployment_clients={item.intent_id for item in session.exec(select(ExactPaperOrderRecord).where(ExactPaperOrderRecord.deployment_id==deployment_id))}
    turnover+=sum((item.remaining_quantity*(item.maximum_price_usd or D(0)) for item in snapshot.open_orders if item.client_order_id in deployment_clients),D(0))
    for reservation in session.exec(select(PaperReservationRecord).where(PaperReservationRecord.account_key==key).where(PaperReservationRecord.active==True)):
        attempt=require(session,PaperExecutionAttemptRecord,reservation.attempt_id)
        if attempt.client_order_id in deployment_clients and attempt.client_order_id not in remote:
            turnover+=D(reservation.quantity)*D(reservation.price_usd)
    if turnover+order.maximum_notional_usd>terms.capital_usd*policy.max_turnover_fraction:
        raise ConflictError("Entry exceeds deployment executed and pending turnover")


class DeploymentRepository(ResearchRepository):
    def validate_evaluation_request(self,identifier,request):
        with self.sessions() as session:
            record=require(session,StrategyDeploymentRecord,identifier)
            self._revision(record,request)
            if record.state!="paper_active" or not record.active_terms_id:
                raise ConflictError("Only an active reviewed deployment can evaluate new targets")
            source=require(session,DatasetSnapshotRecord,request.snapshot_id)
            if source.evidence_kind!="prospective":
                raise ConflictError("Deployment evaluation requires a prospective snapshot")
            if request.as_of>now_utc():
                raise ConflictError("A prospective decision cannot use a future information cutoff")
        return record

    def evaluation_failed(self,identifier,request,stage,error_type,*,job_fence=None):
        with self.transaction() as session:
            if job_fence:
                from tradingagents.research.deployment_jobs import live_job
                live_job(session,*job_fence)
            record=require(session,StrategyDeploymentRecord,identifier)
            affected=record.revision==request.expected_revision and record.state=="paper_active"
            if affected:
                record.state="paused";record.revision+=1;record.updated_at=now_utc();session.add(record)
            self._event(session,record,"evaluation_failed",request.actor,request.reason,
                {"request":request.model_dump(mode="json"),"request_hash":content_hash(request),
                 "stage":stage,"error_type":error_type,"entries_paused":affected,
                 "capital_retained":record.active_terms_id is not None,
                 "message":"No new target was produced. Restore the input or account observation and obtain a fresh funding review before resuming."})
        return record

    def create(self, request: DeploymentInput):
        digest=content_hash(request)
        with self.transaction() as session:
            existing=session.exec(select(StrategyDeploymentRecord).where(StrategyDeploymentRecord.idempotency_key==request.idempotency_key)).first()
            if existing:
                if existing.request_hash!=digest: raise ConflictError("Deployment idempotency key belongs to different terms")
                return existing
            version=require(session,StrategyVersionRecord,request.version_id)
            experiment=require(session,ExperimentRecord,request.experiment_id)
            plan=require(session,ResearchPlanRecord,experiment.plan_id)
            if version.strategy_id!=experiment.strategy_id or version.version_id not in plan.payload["version_ids"]:
                raise ConflictError("Deployment version was not part of this evidence experiment")
            self._validate_terms(version,request.terms)
            terms=DeploymentTermsRecord(deployment_id="pending",content_hash=content_hash(request.terms),payload=request.terms.model_dump(mode="json"))
            record=StrategyDeploymentRecord(name=request.name,version_id=request.version_id,experiment_id=request.experiment_id,
                account_key=account_key(request.account),account=request.account.model_dump(mode="json"),
                idempotency_key=request.idempotency_key,request_hash=digest,pending_terms_id=terms.terms_id)
            terms.deployment_id=record.deployment_id
            session.add(record);session.flush();session.add(terms)
            self._event(session,record,"draft_created","requester","Paper review requested; no capital or order authority granted",{"request_hash":digest})
        return record

    def list(self):
        with self.sessions() as session:
            return list(session.exec(select(StrategyDeploymentRecord).order_by(StrategyDeploymentRecord.created_at.desc())))

    def candidates(self):
        with self.sessions() as session:
            experiments=list(session.exec(select(ExperimentRecord).where(ExperimentRecord.state=="completed").order_by(ExperimentRecord.created_at.desc()).limit(100)))
            result=[]
            for experiment in experiments:
                if not experiment.result: continue
                report=EvidenceReport.model_validate(experiment.result["report"])
                strategy=require(session,StrategyRecord,experiment.strategy_id)
                for assessment in report.assessments:
                    version=require(session,StrategyVersionRecord,assessment.version_id)
                    result.append({"strategy_name":strategy.name,"version_id":version.version_id,"experiment_id":experiment.experiment_id,
                        "created_at":experiment.created_at,"evidence_status":assessment.evidence_status,"evidence_kind":report.snapshot_kind,"spec":version.payload["spec"]})
            return result

    def detail(self, identifier):
        with self.sessions() as session:
            record=require(session,StrategyDeploymentRecord,identifier)
            latest=session.exec(select(PaperReconciliationRecord).where(PaperReconciliationRecord.account_key==record.account_key).order_by(PaperReconciliationRecord.created_at.desc())).first()
            return {"deployment":record,"terms":require(session,DeploymentTermsRecord,record.pending_terms_id),
                "active_terms":session.get(DeploymentTermsRecord,record.active_terms_id) if record.active_terms_id else None,
                "reviews":list(session.exec(select(PromotionReviewRecord).where(PromotionReviewRecord.deployment_id==identifier).order_by(PromotionReviewRecord.created_at.desc()))),
                "events":list(session.exec(select(DeploymentEventRecord).where(DeploymentEventRecord.deployment_id==identifier).order_by(DeploymentEventRecord.created_at))),
                "orders":list(session.exec(select(ExactPaperOrderRecord).where(ExactPaperOrderRecord.deployment_id==identifier))),
                "programs":list(session.exec(select(DeploymentProgramLink).where(DeploymentProgramLink.deployment_id==identifier))),
                "evaluations":list(session.exec(select(DeploymentEvaluationRecord).where(DeploymentEvaluationRecord.deployment_id==identifier).order_by(DeploymentEvaluationRecord.created_at.desc(),DeploymentEvaluationRecord.evaluation_id.desc()))),
                "evaluation_jobs":list(session.exec(select(DeploymentEvaluationJob).where(DeploymentEvaluationJob.deployment_id==identifier).order_by(DeploymentEvaluationJob.created_at.desc()).limit(100))),
                "actual_fills":[fill for fill in latest.report["fills"] if fill["executor"]==f"deployment:{identifier}"] if latest else [],
                "observed_at":latest.observed_at if latest else None,
                "attributed_positions":[position for position in latest.report["positions"] if D(position["owners"].get(f"deployment:{identifier}","0"))>0] if latest else [],
                "account_reconciled":latest.report["reconciled"] if latest else False}

    def review(self, identifier, action: DeploymentAction, reconciliation_id):
        with self.transaction() as session:
            record=require(session,StrategyDeploymentRecord,identifier);self._revision(record,action)
            if record.state not in {"draft","paper_review","paused"}: raise ConflictError("Pause an active deployment before requesting a new review")
            terms=DeploymentTerms.model_validate(require(session,DeploymentTermsRecord,record.pending_terms_id).payload)
            receipt,snapshot=observed_account(session,reconciliation_id,record.account_key,terms.execution_policy)
            evidence=self._evidence(session,record)
            capacity=funding_capacity(session,record.account_key,snapshot,receipt.report,terms.capital_usd,identifier)
            from tradingagents.research.deployment_performance import allocation_proposal
            allocation=allocation_proposal(session,record,receipt,terms.capital_usd)
            gates=[*evidence["gates"],
                {"name":"broker_paper_account","passed":snapshot.evidence_kind=="broker_paper","detail":"An actual paper provider is required; fixture execution cannot become an investment deployment"},
                {"name":"funding_capacity","passed":capacity.allowed,"detail":"Other envelopes, manual holdings and pending buys are included; unconfirmed sells provide no funding"},
                {"name":"drawdown","passed":snapshot.drawdown_fraction<terms.execution_policy.max_drawdown_fraction,"detail":"Current reconciled drawdown must be below the frozen intervention threshold"}]
            record.state="paper_review";record.revision+=1;record.updated_at=now_utc()
            payload={"version_id":record.version_id,"version_hash":evidence["version_hash"],"experiment_id":record.experiment_id,"evidence_hash":evidence["evidence_hash"],
                "terms":terms.model_dump(mode="json"),"account":account_frame(snapshot),"funding":capacity.model_dump(mode="json"),"allocation":allocation,"gates":gates,
                "eligible":all(gate["passed"] for gate in gates),"per_order_human_approval":True}
            review=PromotionReviewRecord(deployment_id=identifier,deployment_revision=record.revision,terms_id=record.pending_terms_id,
                reconciliation_id=reconciliation_id,content_hash=content_hash(payload),payload=payload,expires_at=now_utc()+timedelta(minutes=5))
            session.add(record);session.add(review)
            self._event(session,record,"review_prepared",action.actor,action.reason,{"review_id":review.review_id,"review_hash":review.content_hash,"eligible":payload["eligible"]})
        return review

    def activate(self, identifier, action: DeploymentApproval, reconciliation_id, *, resume=False):
        with self.transaction() as session:
            record=require(session,StrategyDeploymentRecord,identifier);self._revision(record,action)
            if record.state!="paper_review": raise ConflictError("Activation requires a current paper review")
            if bool(record.active_terms_id)!=resume: raise ConflictError("Use resume for a previously activated deployment, or activate for a new one")
            review=require(session,PromotionReviewRecord,action.review_id)
            if review.deployment_id!=identifier or review.deployment_revision!=record.revision or review.terms_id!=record.pending_terms_id or review.content_hash!=action.expected_hash:
                raise ConflictError("Approval does not match the displayed deployment review")
            if review.expires_at<=now_utc() or not review.payload["eligible"]: raise ConflictError("Review is expired or its evidence/funding gates are not met")
            terms=DeploymentTerms.model_validate(review.payload["terms"])
            receipt,snapshot=observed_account(session,reconciliation_id,record.account_key,terms.execution_policy)
            if account_frame(snapshot)!=review.payload["account"]:
                raise ConflictError("Account economics changed after review; prepare a fresh review")
            evidence=self._evidence(session,record)
            if evidence["evidence_hash"]!=review.payload["evidence_hash"] or not all(g["passed"] for g in evidence["gates"]):
                raise ConflictError("Research evidence changed or no longer qualifies")
            capacity=funding_capacity(session,record.account_key,snapshot,receipt.report,terms.capital_usd,identifier)
            if not capacity.allowed: raise ConflictError("Capital is already allocated or does not cover current exposure")
            from tradingagents.research.deployment_performance import allocation_proposal,record_allocation
            allocation=allocation_proposal(session,record,receipt,terms.capital_usd)
            if review.payload.get("allocation")!=allocation:
                raise ConflictError("Deployment allocation changed after review; prepare a fresh review")
            record.state="paper_active";record.active_terms_id=review.terms_id;record.active_review_id=review.review_id;record.revision+=1;record.updated_at=now_utc()
            session.add(record)
            name="resumed" if resume else "activated"
            record_allocation(session,record,allocation,receipt,action.actor,name,review_id=review.review_id)
            self._event(session,record,name,action.actor,action.reason,{"review_id":review.review_id,"review_hash":review.content_hash,"reconciliation_id":reconciliation_id})
            session.add(ApprovalLedgerRecord(room_id="market",source="strategy_deployment",entity_type="strategy_deployment",entity_id=identifier,
                action="accept",actor=action.actor,summary="Human approval of paper deployment and funding; every order still requires its own approval",payload={"review_id":review.review_id,"review_hash":review.content_hash,"action":name}))
        return record

    def pause(self, identifier, action: DeploymentAction):
        with self.transaction() as session:
            record=require(session,StrategyDeploymentRecord,identifier);self._revision(record,action)
            if record.state not in {"paper_active","paper_review","paused"}: raise ConflictError("Only an active or reviewed deployment can be paused")
            record.state="paused";record.revision+=1;record.updated_at=now_utc();session.add(record)
            self._event(session,record,"paused",action.actor,action.reason,{"cancel_unfilled_entries":True,"liquidate_positions":False,"capital_retained":record.active_terms_id is not None})
        return record

    def review_decision(self, identifier, action: DeploymentReviewDecision):
        with self.transaction() as session:
            record=require(session,StrategyDeploymentRecord,identifier);self._revision(record,action)
            review=require(session,PromotionReviewRecord,action.review_id)
            if record.state!="paper_review" or review.deployment_id!=identifier or review.deployment_revision!=record.revision or review.content_hash!=action.expected_hash:
                raise ConflictError("Decision does not match the current displayed review")
            record.state="paused" if record.active_terms_id else "draft";record.revision+=1;record.updated_at=now_utc();session.add(record)
            self._event(session,record,"review_"+action.decision,action.actor,action.reason,{"review_id":review.review_id,"review_hash":review.content_hash})
            session.add(ApprovalLedgerRecord(room_id="market",source="strategy_deployment",entity_type="strategy_deployment",entity_id=identifier,
                action=action.decision,actor=action.actor,summary=action.reason,payload={"review_id":review.review_id,"review_hash":review.content_hash,"capital_retained":bool(record.active_terms_id)}))
        return record

    def change_capital(self, identifier, action: CapitalRevision):
        with self.transaction() as session:
            record=require(session,StrategyDeploymentRecord,identifier);self._revision(record,action)
            if record.state not in {"draft","paused","paper_review"}: raise ConflictError("Pause before changing capital or execution terms")
            self._validate_terms(require(session,StrategyVersionRecord,record.version_id),action.terms)
            terms=DeploymentTermsRecord(deployment_id=identifier,content_hash=content_hash(action.terms),payload=action.terms.model_dump(mode="json"))
            record.pending_terms_id=terms.terms_id;record.state="paused" if record.active_terms_id else "draft";record.revision+=1;record.updated_at=now_utc()
            session.add(terms);session.add(record)
            self._event(session,record,"terms_proposed",action.actor,action.reason,{"terms_id":terms.terms_id,"terms_hash":terms.content_hash,"old_envelope_retained_until_approval":bool(record.active_terms_id)})
        return record

    def retire(self, identifier, action: DeploymentAction, reconciliation_id):
        with self.transaction() as session:
            record=require(session,StrategyDeploymentRecord,identifier);self._revision(record,action)
            if record.state not in {"draft","paper_review","paused"}: raise ConflictError("Pause before retiring a deployment")
            terms=DeploymentTerms.model_validate(require(session,DeploymentTermsRecord,record.pending_terms_id).payload)
            receipt,snapshot=observed_account(session,reconciliation_id,record.account_key,terms.execution_policy,new_risk=False)
            capacity=funding_capacity(session,record.account_key,snapshot,receipt.report,terms.capital_usd,identifier)
            orders=list(session.exec(select(ExactPaperOrderRecord).where(ExactPaperOrderRecord.deployment_id==identifier)))
            has_holdings=any(D(p["owners"].get(f"deployment:{identifier}","0"))>0 for p in receipt.report["positions"])
            spec=StrategySpec.model_validate(require(session,StrategyVersionRecord,record.version_id).payload["spec"])
            symbols={instrument.symbol for instrument in spec.universe}
            if has_holdings or any(o.state not in TERMINAL for o in orders) or any(o.symbol in symbols for o in snapshot.open_orders):
                raise ConflictError("Retirement requires no attributed holdings or outstanding orders; it never silently liquidates")
            from tradingagents.research.deployment_performance import allocation_proposal,record_allocation,flows_for
            allocation=allocation_proposal(session,record,receipt,D(0),retire=True) if record.active_terms_id and flows_for(session,identifier) else None
            record.state="retired";record.revision+=1;record.updated_at=now_utc();session.add(record)
            if allocation: record_allocation(session,record,allocation,receipt,action.actor,"retired")
            self._event(session,record,"retired",action.actor,action.reason,{"reconciliation_id":reconciliation_id,"capital_released":True})
        return record

    @staticmethod
    def _revision(record,action):
        if record.revision!=action.expected_revision: raise ConflictError("Deployment changed; reload before this action")

    @staticmethod
    def _validate_terms(version,terms):
        spec=StrategySpec.model_validate(version.payload["spec"])
        for key in ("max_position_fraction","max_group_fraction","max_turnover_fraction","max_drawdown_fraction"):
            if getattr(terms.execution_policy,key)>getattr(spec.risk,key): raise ConflictError("Deployment cannot loosen the frozen strategy risk limits")
        if terms.execution_policy.cash_reserve_fraction<spec.risk.cash_reserve_fraction:
            raise ConflictError("Deployment cannot reduce the frozen strategy cash reserve")

    @staticmethod
    def _evidence(session,record):
        experiment=require(session,ExperimentRecord,record.experiment_id)
        version=require(session,StrategyVersionRecord,record.version_id)
        gates=[]
        def gate(name,passed,detail): gates.append({"name":name,"passed":bool(passed),"detail":detail})
        gate("completed_experiment",experiment.state=="completed" and bool(experiment.result),"The experiment must have a persisted completed result")
        gate("version_integrity",content_hash(version.payload)==version.content_hash,"The exact immutable version is pinned")
        if experiment.result:
            result=ExperimentResult.model_validate(experiment.result)
            report=EvidenceReport.model_validate(result.report)
            assessment=next((a for a in report.assessments if a.version_id==record.version_id),None)
            snapshot=require(session,DatasetSnapshotRecord,experiment.snapshot_id)
            manifest=SnapshotManifest.model_validate(snapshot.payload)
            gate("eligible_version",assessment is not None and assessment.evidence_status=="eligible_for_paper_review" and bool(assessment.checks) and all(c.passed for c in assessment.checks),"This version, rather than another trial, must meet all frozen evidence criteria")
            gate("genuine_holdout",experiment.evaluation=="holdout" and report.evaluation=="holdout" and manifest.evidence_kind!="fixture" and report.snapshot_kind!="fixture" and manifest.availability not in {"synthetic","unverified"},"Synthetic, unverified and development results cannot authorize investment deployment")
            gate("report_integrity",result.artifacts.get("report")==content_hash(result.report),"The evidence report must match its persisted artifact fingerprint")
            gate("report_provenance",result.manifest_hash==snapshot.content_hash and report.snapshot_manifest_hash==snapshot.content_hash and report.snapshot_kind==manifest.evidence_kind and result.engine_build==report.engine_build,"Report provenance must agree with the original snapshot and execution build")
            gate("equity_reference",report.equity_reference is not None,"A predeclared equity reference is required")
            if isinstance(StrategySpec.model_validate(version.payload["spec"]).rules, GuidanceRules):
                paired = [arm.paired_events for arm in report.arm_comparisons if record.version_id in {arm.challenger_version_id,arm.control_version_id}]
                gate("paired_event_accounting",bool(paired) and all(p and p.reconciled and p.artifact_hash in result.artifacts.values() for p in paired),
                     "Guidance promotion needs saved paired event accounting; earlier aggregate-only reports remain exploratory")
        return {"gates":gates,"version_hash":version.content_hash,"evidence_hash":content_hash(experiment.result or {})}

    @staticmethod
    def _event(session,record,action,actor,reason,payload):
        session.add(DeploymentEventRecord(deployment_id=record.deployment_id,revision=record.revision,action=action,actor=actor,reason=reason,payload=payload))


def install_deployment_guards(engine):
    with engine.begin() as connection:
        for table in ("research_deployment_terms","research_promotion_reviews","research_deployment_events","research_deployment_programs","research_deployment_evaluations","research_deployment_order_targets","research_deployment_capital_flows"):
            for action in ("UPDATE","DELETE"):
                connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'deployment review history is immutable'); END"))
        fields=("deployment_id","name","version_id","experiment_id","account_key","account","idempotency_key","request_hash","created_at")
        condition=" OR ".join(f'OLD."{field}" IS NOT NEW."{field}"' for field in fields)
        connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS deployment_identity_pin BEFORE UPDATE ON research_deployments WHEN {condition} BEGIN SELECT RAISE(ABORT, 'deployment identity is immutable'); END"))
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS deployment_no_delete BEFORE DELETE ON research_deployments BEGIN SELECT RAISE(ABORT, 'deployment history is immutable'); END"))
