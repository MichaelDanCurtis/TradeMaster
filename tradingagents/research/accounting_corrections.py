"""Reviewed selection of observed source revisions; no source evidence is edited."""
from collections import defaultdict

from sqlmodel import select

from tradingagents.research.accounting_contracts import AccountActivity
from tradingagents.research.accounting_models import (
    PaperAccountActivityRecord, PaperActivityRevisionRecord, PaperCorrectionApprovalRecord,
    PaperCorrectionReviewRecord,
)
from tradingagents.research.contracts import content_hash
from tradingagents.research.repository import ConflictError, require


def correction_state(session, key, previous, request=None, overrides=()):
    from tradingagents.research.accounting_repository import _economic_hash
    originals = list(session.exec(select(PaperAccountActivityRecord).where(PaperAccountActivityRecord.account_key==key)))
    revisions = list(session.exec(select(PaperActivityRevisionRecord).where(PaperActivityRevisionRecord.account_key==key)))
    variants = defaultdict(dict)
    selected = {}
    for row in originals:
        if content_hash(row.activity) != row.content_hash:
            raise ConflictError("Original source activity failed integrity verification")
        variants[row.source_id][row.content_hash] = AccountActivity.model_validate(row.activity)
        selected[row.source_id] = row.content_hash
    for row in revisions:
        if content_hash(row.activity) != row.revised_hash:
            raise ConflictError("Revised source activity failed integrity verification")
        variants[row.source_id][row.revised_hash] = AccountActivity.model_validate(row.activity)
    approvals = list(session.exec(select(PaperCorrectionApprovalRecord).where(PaperCorrectionApprovalRecord.account_key==key)
        .order_by(PaperCorrectionApprovalRecord.created_at,PaperCorrectionApprovalRecord.correction_id)))
    seen, omitted = {}, set()
    for approval in approvals:
        review = require(session,PaperCorrectionReviewRecord,approval.review_id)
        if review.account_key != key or content_hash(review.payload) != review.content_hash:
            raise ConflictError("Correction approval evidence failed integrity verification")
        omitted = set(review.payload["excluded_observation_ids"])
        for change in review.payload["changes"]:
            selected[change["source_id"]] = change["selected_hash"]
            seen[change["source_id"]] = set(change["seen_hashes"])
    for change in overrides:
        selected[change["source_id"]] = change["selected_hash"]
        seen[change["source_id"]] = set(change["seen_hashes"])
    latest_source = {}
    ordered = sorted(previous,key=lambda row:(row.created_at,row.reconciliation_id))
    for row in ordered:
        for raw in row.request["batch"]["activities"]:
            latest_source[raw["source_id"]] = AccountActivity.model_validate(raw)
    if request:
        latest_source.update({a.source_id:a for a in request.batch.activities})
    pending, activities = [], []
    for source_id, choices in variants.items():
        chosen = choices.get(selected[source_id])
        if chosen is None: raise ConflictError("Reviewed correction version is unavailable")
        activities.append(chosen)
        current = latest_source.get(source_id)
        if len(choices)>1 and (seen.get(source_id) != set(choices) or current is None or _economic_hash(current)!=_economic_hash(chosen)):
            pending.append(source_id)
    ids = [row.correction_id for row in approvals]
    state_hash = content_hash({"latest_receipt":ordered[-1].reconciliation_id if ordered else None,
        "variants":{key:sorted(value) for key,value in variants.items()}, "approval_ids":ids,
        "latest_source":{key:_economic_hash(value) for key,value in latest_source.items()}})
    return {"variants":variants,"selected":selected,"pending":sorted(pending),"activities":activities,
            "latest_source":latest_source,"omitted":omitted,"approval_ids":ids,"state_hash":state_hash}


def correction_selection(session,key,previous,request,overrides=()):
    state = correction_state(session,key,previous,request,overrides)
    errors = [{"code":"source_activity_revised","source_id":source,
               "detail":"Observed source versions conflict; review the latest observed correction before using returns"}
              for source in state["pending"]]
    return state["activities"],errors,state["omitted"],state["approval_ids"]
