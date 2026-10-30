"""Read-only reconstruction of guidance state from immutable execution evidence."""
from datetime import datetime

from sqlmodel import select

from tradingagents.research.contracts import content_hash
from tradingagents.research.deployment_models import DeploymentEvaluationRecord, DeploymentOrderTargetRecord, DeploymentEventRecord
from tradingagents.research.execution_models import ExactPaperOrderRecord, PaperExecutionAttemptRecord
from tradingagents.research.execution_contracts import TERMINAL
from tradingagents.research.repository import require
from tradingagents.research.strategies.guidance_deployment import GuidanceDeploymentContext


def restore_guidance_context(session,record,spec,receipt,snapshot,dataset,as_of):
    activation=session.exec(select(DeploymentEventRecord).where(DeploymentEventRecord.deployment_id==record.deployment_id)
        .where(DeploymentEventRecord.action=="activated").order_by(DeploymentEventRecord.created_at)).first()
    if activation is None:
        raise ValueError("Guidance deployment has no persisted initial activation")
    context=GuidanceDeploymentContext(start_at=activation.created_at)
    evaluations=list(session.exec(select(DeploymentEvaluationRecord).where(DeploymentEvaluationRecord.deployment_id==record.deployment_id)
        .order_by(DeploymentEvaluationRecord.created_at,DeploymentEvaluationRecord.evaluation_id)))
    sources={}
    for kind,items,key in (("notice",dataset.guidance_notices,"notice_id"),("document",dataset.documents,"document_id"),("financial",dataset.financials,"observation_id")):
        for item in items:
            if item.availability.available_at<=as_of:
                sources[f"{kind}:{getattr(item,key)}"]=content_hash(item)
    for evaluation in evaluations:
        state=evaluation.payload.get("guidance_state",{})
        context.consumed_notices.update(state.get("consumed_notices",[]))
        context.event_hashes.update(state.get("event_hashes",{}))
        for identifier,digest in evaluation.payload.get("guidance_source_hashes",{}).items():
            if sources.get(identifier)!=digest:
                raise ValueError("Previously observed guidance sources must be retained unchanged; amendments need distinct source IDs")
    instruments={i.symbol:i.instrument_id for i in spec.universe}
    orders=list(session.exec(select(ExactPaperOrderRecord).where(ExactPaperOrderRecord.deployment_id==record.deployment_id)))
    order_map={order.order_id:order for order in orders}
    # A prepared entry is one attempt even when rejected, expired or never sent.
    for target in session.exec(select(DeploymentOrderTargetRecord).where(DeploymentOrderTargetRecord.deployment_id==record.deployment_id)):
        if target.order["side"]!="buy": continue
        evaluation=require(session,DeploymentEvaluationRecord,target.evaluation_id)
        instrument=instruments.get(target.order["symbol"])
        notice=evaluation.payload.get("entry_notice_ids",{}).get(instrument)
        if not notice:
            raise ValueError("Prepared guidance entry has no frozen source notice")
        context.consumed_notices.add(notice)
    by_broker={}
    for attempt in session.exec(select(PaperExecutionAttemptRecord).where(PaperExecutionAttemptRecord.account_key==record.account_key)):
        if attempt.order_id in order_map and attempt.broker_order_id:
            by_broker[attempt.broker_order_id]=order_map[attempt.order_id]
    for order in orders:
        if order.state in TERMINAL: continue
        if order.state in {"previewed","approved"} and datetime.fromisoformat(order.order["expires_at"])<=snapshot.observed_at: continue
        instrument=instruments.get(order.order["symbol"])
        if instrument:
            (context.pending_entries if order.order["side"]=="buy" else context.pending_exits).add(instrument)
    owner=f"deployment:{record.deployment_id}"
    if "position_cycles" not in receipt.report:
        raise ValueError("Refresh accounting to establish continuous-holding opening fills")
    for cycle in receipt.report["position_cycles"]:
        if cycle["owner"]!=owner: continue
        instrument=instruments.get(cycle["symbol"])
        order=by_broker.get(cycle["entry_broker_order_id"])
        if not instrument or not order or not order.target_id:
            raise ValueError("Guidance holding's opening broker fill has no exact strategy target")
        target=require(session,DeploymentOrderTargetRecord,order.target_id)
        evaluation=require(session,DeploymentEvaluationRecord,target.evaluation_id)
        notice=evaluation.payload.get("entry_notice_ids",{}).get(instrument)
        if not notice:
            raise ValueError("Opening fill cannot be joined to its original guidance notice")
        context.holding_clocks[instrument]={"notice_id":notice,"entry_at":datetime.fromisoformat(cycle["entry_at"])}
    return context,sources
