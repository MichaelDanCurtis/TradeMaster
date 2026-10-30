"""Read-only lineage from portfolio proposals to reconciled native fills.

Local dispatch/acknowledgment times are not remote arrival times. Reference
price differences describe filled shares only; no missed-trade profit is inferred.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal as D

from sqlalchemy import and_,or_,text
from sqlmodel import select

from tradingagents.research.accounting_models import PaperReconciliationRecord
from tradingagents.research.contracts import content_hash
from tradingagents.research.deployment_models import StrategyDeploymentRecord,DeploymentEvaluationRecord,DeploymentOrderTargetRecord
from tradingagents.research.execution_models import ExactPaperOrderRecord,PaperExecutionAttemptRecord,PaperExecutionEventRecord
from tradingagents.research.repository import ConflictError,require
from tradingagents.ui.models import ApprovalRecord,now_utc


def _date(value):
    return datetime.fromisoformat(value) if value else None


def _seconds(start,end):
    # A negative interval indicates incompatible clocks, not a zero delay.
    return (end-start).total_seconds() if start and end and end>=start else None


def _outcome(delta,order,attempt,filled,approved,as_of,deadline,superseded,approval_valid=True):
    if not delta: return "unchanged"
    if order is None:
        if superseded: return "superseded_without_ticket"
        return "window_elapsed_without_ticket" if deadline and as_of>=deadline else "no_ticket_prepared"
    if attempt is None:
        if order.state=="canceled": return "canceled_before_dispatch"
        if _date(order.order.get("expires_at"))<=as_of: return "approval_window_expired_without_dispatch"
        if superseded: return "superseded_before_dispatch"
        if approved and not approval_valid: return "approval_revoked_before_dispatch"
        return "approved_awaiting_dispatch" if approved else "awaiting_human_approval"
    if attempt.state in {"unknown","dispatching"}: return "submission_unresolved"
    if filled is None: return "account_reconciliation_required"
    if D(attempt.filled_quantity)!=filled: return "fill_reconciliation_pending"
    if filled>=abs(delta): return "filled"
    if order.state=="pending_cancel" and attempt.state not in {"canceled","expired","rejected","filled"}:
        return "partially_filled_cancellation_pending" if filled else "cancellation_pending"
    if attempt.state in {"canceled","expired","rejected"}:
        return f"partially_filled_then_{attempt.state}" if filled else f"broker_{attempt.state}"
    return "partially_filled_open" if filled else "acknowledged_without_reconciled_fill"


def _row(evaluation,proposal,order,attempt,events,approvals,fills,reconciled,as_of,superseded):
    delta=proposal["delta_quantity"]
    approved=[a for a in approvals if a.action=="approve_order" and a.after_payload.get("order_hash")==order.content_hash] if order else []
    approved.sort(key=lambda a:(a.created_at,a.approval_id))
    first_approval=approved[0] if approved else None
    decisions=sorted([a for a in approvals if a.action in {"approve_order","reject_order","revoke_order","cancel_order"}],key=lambda a:(a.created_at,a.approval_id))
    approval_valid=bool(decisions and decisions[-1].action=="approve_order" and decisions[-1].after_payload.get("status")=="approved" and order and decisions[-1].after_payload.get("order_hash")==order.content_hash)
    used_approval=next((a for a in approved if attempt and a.approval_id==attempt.approval_id),None)
    acknowledgment=next((e for e in events if e.kind=="broker_observed"),None)
    cancellation=next((e for e in events if e.kind in {"cancel_requested","preview_canceled"}),None)
    decision=_date(evaluation.payload.get("as_of"));opens=_date(evaluation.payload.get("execution_opens_at"))
    deadline=_date(evaluation.payload.get("execution_deadline"))
    actual=sorted(fills,key=lambda f:(_date(f["effective_at"]),f["source_id"])) if reconciled else []
    filled=sum((D(f["quantity"]) for f in actual),D(0)) if reconciled else None
    first_fill=_date(actual[0]["effective_at"]) if actual else None
    last_fill=_date(actual[-1]["effective_at"]) if actual else None
    notional=sum((D(f["quantity"])*D(f["price_usd"]) for f in actual),D(0))
    fees=sum((D(f["fee_usd"]) for f in actual),D(0))
    reference=D(proposal["reference_price_usd"]) if proposal.get("reference_price_usd") else None
    difference=(notional-filled*reference)*(1 if delta>0 else -1) if filled and reference is not None else None
    timeline={"decision_cutoff":decision,"evaluated_at":evaluation.created_at,"execution_opens_at":opens,"execution_deadline":deadline,
        "prepared_at":order.created_at if order else None,"first_approved_at":first_approval.created_at if first_approval else None,
        "dispatch_approval_at":used_approval.created_at if used_approval else None,"dispatch_claimed_at":attempt.created_at if attempt else None,
        "first_broker_response_observed_at":acknowledgment.created_at if acknowledgment else None,
        "cancellation_requested_at":cancellation.created_at if cancellation else None,"first_reconciled_fill_at":first_fill,"last_reconciled_fill_at":last_fill}
    delays={"evaluation_to_preparation_seconds":_seconds(evaluation.created_at,timeline["prepared_at"]),
        "preparation_to_first_approval_seconds":_seconds(timeline["prepared_at"],timeline["first_approved_at"]),
        "used_approval_to_dispatch_claim_seconds":_seconds(timeline["dispatch_approval_at"],timeline["dispatch_claimed_at"]),
        "dispatch_claim_to_broker_observation_seconds":_seconds(timeline["dispatch_claimed_at"],timeline["first_broker_response_observed_at"]),
        "execution_open_to_first_fill_seconds":_seconds(opens,first_fill),
        "dispatch_claim_to_first_fill_seconds":_seconds(timeline["dispatch_claimed_at"],first_fill)}
    notes=[]
    if not reconciled: notes.append("No reconciled account receipt is available; actual-fill quantities and costs are unavailable.")
    if attempt and filled is not None and D(attempt.filled_quantity)!=filled:
        notes.append("The order acknowledgment and reconciled fill activity disagree or cover different observation times; refresh account reconciliation.")
    if not actual: notes.append("No reconciled fill is linked. No execution cost or missed-trade return is estimated.")
    if first_fill and opens and first_fill<opens: notes.append("Fill precedes the declared execution window; timing requires review.")
    if first_fill and attempt and first_fill<attempt.created_at: notes.append("Fill precedes the local dispatch claim; source clock ordering requires review.")
    if superseded: notes.append("A newer portfolio evaluation exists; this row preserves the earlier proposal and its execution history.")
    if filled is not None and filled>abs(delta): notes.append("Reconciled quantity exceeds the original proposal; investigate source units or order changes.")
    return {"evaluation_id":evaluation.evaluation_id,"version_id":evaluation.payload.get("version_id"),"instrument_id":proposal["instrument_id"],
        "symbol":proposal["symbol"],"side":"buy" if delta>0 else "sell" if delta<0 else "hold",
        "observed_quantity_at_evaluation":proposal["current_quantity"],"proposed_quantity":proposal["desired_quantity"],"proposed_delta":delta,
        "order_id":order.order_id if order else None,"intent_id":order.intent_id if order else None,
        "order_hash":order.content_hash if order else None,"order_state":order.state if order else None,
        "prepared_quantity":order.order["quantity"] if order else None,"ever_approved_quantity":order.order["quantity"] if first_approval else None,
        "dispatch_approved_quantity":order.order["quantity"] if used_approval else None,
        "dispatch_approval_id":used_approval.approval_id if used_approval else None,
        "broker_order_id":attempt.broker_order_id if attempt else None,"broker_observed_filled_quantity":attempt.filled_quantity if attempt else None,
        "reconciled_fill_quantity":str(filled) if filled is not None else None,
        "unfilled_proposed_quantity":str(max(D(0),abs(delta)-filled)) if filled is not None else None,
        "fill_fraction":str(filled/abs(delta)) if filled is not None and delta else None,
        "average_fill_price_usd":str(notional/filled) if filled else None,
        "fill_fees_usd":str(fees) if actual else None,"decision_reference_price_usd":str(reference) if reference is not None else None,
        "filled_price_difference_usd":str(difference) if difference is not None else None,
        "filled_price_difference_plus_fees_usd":str(difference+fees) if difference is not None else None,
        "outcome":_outcome(delta,order,attempt,filled,first_approval,as_of,deadline,superseded,approval_valid),
        "timeline":{k:v.isoformat() if v else None for k,v in timeline.items()},"delays":delays,
        "fills":actual,"events":[{"event_id":e.event_id,"kind":e.kind,"created_at":e.created_at.isoformat(),"actor":e.payload.get("actor"),
            "observed_status":e.payload.get("observation",{}).get("status")} for e in events],"limitations":notes}


def execution_attribution(sessions,identifier,*,before=None,limit=10):
    if not 1<=limit<=25: raise ValueError("Attribution page size must be between 1 and 25 evaluations")
    as_of=now_utc()
    with sessions() as session:
        # A coherent read snapshot; this path makes no broker calls or mutations.
        session.execute(text("BEGIN"))
        record=require(session,StrategyDeploymentRecord,identifier)
        query=select(DeploymentEvaluationRecord).where(DeploymentEvaluationRecord.deployment_id==identifier)
        newest=session.exec(query.order_by(DeploymentEvaluationRecord.created_at.desc(),DeploymentEvaluationRecord.evaluation_id.desc())).first()
        if before:
            cursor=require(session,DeploymentEvaluationRecord,before)
            if cursor.deployment_id!=identifier: raise ConflictError("Attribution cursor belongs to another deployment")
            query=query.where(or_(DeploymentEvaluationRecord.created_at<cursor.created_at,and_(DeploymentEvaluationRecord.created_at==cursor.created_at,DeploymentEvaluationRecord.evaluation_id<cursor.evaluation_id)))
        evaluations=list(session.exec(query.order_by(DeploymentEvaluationRecord.created_at.desc(),DeploymentEvaluationRecord.evaluation_id.desc()).limit(limit+1)))
        more=len(evaluations)>limit;evaluations=evaluations[:limit];ids=[e.evaluation_id for e in evaluations]
        orders=list(session.exec(select(ExactPaperOrderRecord).join(DeploymentOrderTargetRecord,ExactPaperOrderRecord.target_id==DeploymentOrderTargetRecord.target_id)
            .where(DeploymentOrderTargetRecord.evaluation_id.in_(ids)).where(ExactPaperOrderRecord.deployment_id==identifier)))
        targets=list(session.exec(select(DeploymentOrderTargetRecord).where(DeploymentOrderTargetRecord.evaluation_id.in_(ids))))
        # Joins keep bind-parameter count bounded by evaluation page size, even
        # with a large universe and multiple events per order.
        def scoped(model,on):
            return select(model).join(ExactPaperOrderRecord,on).join(DeploymentOrderTargetRecord,ExactPaperOrderRecord.target_id==DeploymentOrderTargetRecord.target_id).where(DeploymentOrderTargetRecord.evaluation_id.in_(ids)).where(ExactPaperOrderRecord.deployment_id==identifier)
        attempts=list(session.exec(scoped(PaperExecutionAttemptRecord,PaperExecutionAttemptRecord.order_id==ExactPaperOrderRecord.order_id)))
        events=list(session.exec(scoped(PaperExecutionEventRecord,PaperExecutionEventRecord.order_id==ExactPaperOrderRecord.order_id)))
        approvals=list(session.exec(scoped(ApprovalRecord,ApprovalRecord.intent_id==ExactPaperOrderRecord.intent_id)))
        receipt=session.exec(select(PaperReconciliationRecord).where(PaperReconciliationRecord.account_key==record.account_key)
            .order_by(PaperReconciliationRecord.created_at.desc(),PaperReconciliationRecord.reconciliation_id.desc())).first()
        reconciled=bool(receipt and receipt.report["reconciled"])
        fills=receipt.report.get("fills",[]) if receipt else []
        by_target={o.target_id:o for o in orders};by_proposal={(t.evaluation_id,t.order["symbol"]):by_target.get(t.target_id) for t in targets}
        by_attempt={a.order_id:a for a in attempts};by_events=defaultdict(list);by_approvals=defaultdict(list);by_fills=defaultdict(list)
        for event in sorted(events,key=lambda e:(e.created_at,e.event_id)): by_events[event.order_id].append(event)
        for approval in approvals: by_approvals[approval.intent_id].append(approval)
        for fill in fills:
            if fill["executor"]==f"deployment:{identifier}": by_fills[(fill["broker_order_id"],fill["symbol"],fill["side"])].append(fill)
        rows=[]
        for evaluation in evaluations:
            for proposal in evaluation.payload.get("portfolio",[]):
                order=by_proposal.get((evaluation.evaluation_id,proposal["symbol"]));attempt=by_attempt.get(order.order_id) if order else None
                linked=by_fills[(attempt.broker_order_id,proposal["symbol"],order.order["side"])] if attempt and attempt.broker_order_id else []
                row = _row(evaluation,proposal,order,attempt,by_events[order.order_id] if order else [],by_approvals[order.intent_id] if order else [],linked,reconciled,as_of,newest.evaluation_id!=evaluation.evaluation_id)
                row["protective_fills"] = [fill for fill in fills if reconciled and attempt and attempt.broker_order_id
                    and fill.get("parent_broker_order_id") == attempt.broker_order_id]
                rows.append(row)
        inputs={"evaluations":[{"id":e.evaluation_id,"payload_hash":content_hash(e.payload)} for e in evaluations],
            "orders":[o.model_dump(mode="json") for o in orders],"attempts":[a.model_dump(mode="json") for a in attempts],
            "events":[{"id":e.event_id,"payload_hash":content_hash(e.payload),"at":e.created_at.isoformat()} for e in events],
            "approvals":[a.model_dump(mode="json") for a in approvals],"reconciliation_id":receipt.reconciliation_id if receipt else None,
            "reconciliation_report_hash":content_hash(receipt.report) if receipt else None,"as_of":as_of.isoformat()}
        return {"schema_version":1,"deployment_id":identifier,"deployment_name":record.name,"version_id":record.version_id,
            "generated_at":as_of.isoformat(),"account_observed_at":receipt.observed_at.isoformat() if receipt else None,
            "account_reconciled":reconciled,"reconciliation_id":receipt.reconciliation_id if receipt else None,
            "evidence_kind":receipt.report.get("evidence_kind") if receipt else None,"input_hash":content_hash(inputs),
            "evaluations":[{"evaluation_id":e.evaluation_id,"created_at":e.created_at.isoformat(),"status":e.payload.get("status"),"reason":e.payload.get("reason")} for e in evaluations],
            "next_cursor":evaluations[-1].evaluation_id if more else None,"rows":rows,
            "limitations":["This page is derived from persisted proposals, exact approvals, local execution events and the identified account receipt; it does not submit or reconcile orders.",
                "A dispatch claim does not prove that a request reached the broker. Broker-response times are local observations, not native acceptance timestamps.",
                "Elapsed intervals do not identify causation. Clock conflicts and missing endpoints produce unavailable intervals rather than zero delay.",
                "Price differences use filled shares versus the decision reference. Positive values are adverse for either side; they are not causal delay cost, realized P&L, or estimated profit on unfilled shares.",
                "Repeated portfolio evaluations describe overlapping opportunities. Do not sum their proposed holdings or infer a cumulative return from this table."]}
