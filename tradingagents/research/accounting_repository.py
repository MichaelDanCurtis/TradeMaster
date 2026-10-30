"""Reviewed account baselines, immutable source receipts, and recomputed history."""
import json
import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from platform import python_version
from pydantic import __version__ as pydantic_version

from sqlalchemy import text
from sqlalchemy.orm import defer
from sqlmodel import select

from tradingagents.research.accounting import reconcile_account
from tradingagents.research.account_rounding import equity_reconciles
from tradingagents.research.accounting_lineage import protection_lineage, apply_fill_lineage
from tradingagents.research.accounting_corrections import correction_state, correction_selection
from tradingagents.research.accounting_contracts import AccountActivity, AccountingReconciliation
from tradingagents.research.accounting_models import PaperBaselineRecord, PaperEnrollmentRecord, PaperAccountActivityRecord, PaperActivityRevisionRecord, PaperReconciliationRecord, PaperCorrectionReviewRecord, PaperCorrectionApprovalRecord
from tradingagents.research.contracts import content_hash
from tradingagents.research.execution_contracts import PaperAccountSnapshot
from tradingagents.research.execution_models import ExactPaperOrderRecord, PaperExecutionAttemptRecord
from tradingagents.research.execution_repository import account_key
from tradingagents.research.repository import ConflictError, ResearchRepository, require
from tradingagents.ui.models import ApprovalLedgerRecord, now_utc


# Capture the loaded process build once. Editing files beneath a running API
# must not relabel old in-memory calculations with a newer source fingerprint.
_ACCOUNTING_BUILD = content_hash({"sources":{
    name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
    for name in ("accounting.py", "account_rounding.py", "accounting_contracts.py", "accounting_repository.py", "accounting_lineage.py", "accounting_corrections.py")
}, "python":python_version(), "pydantic":pydantic_version})


class PaperAccountingRepository(ResearchRepository):
    def preview_baseline(self, snapshot: PaperAccountSnapshot):
        _fresh(snapshot)
        key = account_key(snapshot)
        with self.transaction() as session:
            if session.get(PaperEnrollmentRecord, key):
                raise ConflictError("This account already has a reviewed baseline; observation history cannot be reset")
            record = PaperBaselineRecord(account_key=key, content_hash=content_hash(snapshot), snapshot=snapshot.model_dump(mode="json"), expires_at=now_utc()+timedelta(minutes=5))
            session.add(record)
        return record

    def approve_baseline(self, baseline_id: str, expected_hash: str, actor: str):
        if not actor.strip(): raise ValueError("Baseline approval requires a named actor")
        with self.transaction() as session:
            record = require(session, PaperBaselineRecord, baseline_id)
            if record.content_hash != expected_hash:
                raise ConflictError("Approval does not match the displayed account baseline")
            existing = session.get(PaperEnrollmentRecord, record.account_key)
            if existing:
                if existing.baseline_id == record.baseline_id: return existing
                raise ConflictError("Account was already enrolled with a different baseline")
            if record.state != "previewed" or record.expires_at <= now_utc():
                raise ConflictError("Account baseline preview is expired or no longer approvable")
            snapshot = PaperAccountSnapshot.model_validate(record.snapshot)
            enrollment = PaperEnrollmentRecord(account_key=record.account_key, baseline_id=record.baseline_id, provider_id=snapshot.provider_id, account_id=snapshot.account_id, actor=actor)
            session.add(enrollment)
            record.state = "approved"
            session.add(record)
            session.add(ApprovalLedgerRecord(room_id="transactions", source="paper_accounting", entity_type="paper_account_baseline", entity_id=baseline_id,
                action="accept", actor=actor, summary="Begin persisted account observation from this reviewed baseline; earlier returns are excluded",
                payload={"account_key":record.account_key, "baseline_hash":expected_hash, "observed_at":snapshot.observed_at.isoformat(), "evidence_kind":snapshot.evidence_kind}))
        return enrollment

    def baseline(self, key: str):
        with self.sessions() as session:
            enrollment = session.get(PaperEnrollmentRecord, key)
            return session.get(PaperBaselineRecord, enrollment.baseline_id) if enrollment else None

    def list_accounts(self):
        with self.sessions() as session:
            records = list(session.exec(select(PaperEnrollmentRecord).order_by(PaperEnrollmentRecord.approved_at.desc())))
            result = []
            for record in records:
                baseline = require(session, PaperBaselineRecord, record.baseline_id)
                latest = session.exec(select(PaperReconciliationRecord).where(PaperReconciliationRecord.account_key == record.account_key).order_by(PaperReconciliationRecord.created_at.desc()).limit(1)).first()
                result.append({"enrollment":record, "baseline":baseline, "latest":latest})
            return result

    def latest_observed_at(self, key: str):
        with self.sessions() as session:
            require(session, PaperEnrollmentRecord, key)
            return session.exec(select(PaperReconciliationRecord.observed_at)
                .where(PaperReconciliationRecord.account_key == key)
                .order_by(PaperReconciliationRecord.created_at.desc()).limit(1)).first()

    def history(self, key: str):
        with self.sessions() as session:
            require(session, PaperEnrollmentRecord, key)
            return list(session.exec(select(PaperReconciliationRecord).where(PaperReconciliationRecord.account_key == key).order_by(PaperReconciliationRecord.created_at.desc()).limit(250)))

    def reconcile(self, request: AccountingReconciliation):
        key, digest = account_key(request.snapshot), content_hash(request)
        with self.transaction() as session:
            approvals = list(session.exec(select(PaperCorrectionApprovalRecord.correction_id).where(PaperCorrectionApprovalRecord.account_key==key)))
            if approvals: digest = content_hash({"request":request.model_dump(mode="json"),"correction_approval_ids":sorted(approvals)})
            existing = session.exec(select(PaperReconciliationRecord).where(PaperReconciliationRecord.content_hash == digest)).first()
            if existing: return existing
            enrollment = require(session, PaperEnrollmentRecord, key)
            baseline_row = require(session, PaperBaselineRecord, enrollment.baseline_id)
            baseline = PaperAccountSnapshot.model_validate(baseline_row.snapshot)
            if request.snapshot.observed_at <= baseline.observed_at:
                raise ConflictError("New observation must follow the reviewed baseline")
            previous = list(session.exec(select(PaperReconciliationRecord).options(defer(PaperReconciliationRecord.report, raiseload=True)).where(PaperReconciliationRecord.account_key == key).order_by(PaperReconciliationRecord.observed_at)))
            if previous and request.snapshot.observed_at < previous[-1].observed_at:
                raise ConflictError("Account reconciliation cannot move its observation clock backwards")
            for activity in request.batch.activities:
                payload, fingerprint = activity.model_dump(mode="json"), content_hash(activity)
                activity_id = content_hash({"account_key":key, "source_id":activity.source_id})
                known = session.get(PaperAccountActivityRecord, activity_id)
                if known and _economic_hash(AccountActivity.model_validate(known.activity)) != _economic_hash(activity):
                    revision_key = content_hash({"activity_key":activity_id, "economic_revision":_economic_hash(activity)})
                    if not session.get(PaperActivityRevisionRecord, revision_key):
                        session.add(PaperActivityRevisionRecord(revision_key=revision_key, account_key=key, source_id=activity.source_id,
                            previous_hash=known.content_hash, revised_hash=fingerprint, activity=payload))
                elif known is None:
                    session.add(PaperAccountActivityRecord(activity_key=activity_id, account_key=key, source_id=activity.source_id, content_hash=fingerprint, activity=payload))
            session.flush()
            selected, correction_errors, omitted, correction_ids = correction_selection(session, key, previous, request)
            report = _calculate_report(session, key, baseline_row, previous, request, selected, correction_errors, omitted, correction_ids)
            record = PaperReconciliationRecord(content_hash=digest, account_key=key, request=request.model_dump(mode="json"),
                report=json.loads(json.dumps(report, default=_decimal_wire)), observed_at=request.snapshot.observed_at)
            session.add(record)
        return record

    def corrections(self, key):
        with self.sessions() as session:
            require(session,PaperEnrollmentRecord,key)
            previous = list(session.exec(select(PaperReconciliationRecord).options(defer(PaperReconciliationRecord.report, raiseload=True)).where(PaperReconciliationRecord.account_key==key)))
            state = correction_state(session,key,previous)
            reviews = list(session.exec(select(PaperCorrectionReviewRecord).where(PaperCorrectionReviewRecord.account_key==key)
                .order_by(PaperCorrectionReviewRecord.created_at.desc()).limit(50)))
            approvals = list(session.exec(select(PaperCorrectionApprovalRecord).where(PaperCorrectionApprovalRecord.account_key==key)
                .order_by(PaperCorrectionApprovalRecord.created_at.desc()).limit(50)))
            return {"pending_source_ids":state["pending"],"reviews":reviews,"approvals":approvals}

    def preview_corrections(self,key):
        with self.transaction() as session:
            enrollment = require(session,PaperEnrollmentRecord,key)
            baseline = require(session,PaperBaselineRecord,enrollment.baseline_id)
            previous = list(session.exec(select(PaperReconciliationRecord).options(defer(PaperReconciliationRecord.report, raiseload=True)).where(PaperReconciliationRecord.account_key==key)
                .order_by(PaperReconciliationRecord.created_at,PaperReconciliationRecord.reconciliation_id)))
            if not previous: raise ConflictError("Reconcile observed source revisions before requesting correction review")
            latest = previous[-1]
            if latest.observed_at < now_utc()-timedelta(minutes=5):
                raise ConflictError("Refresh account reconciliation before reviewing source corrections")
            request = AccountingReconciliation.model_validate(latest.request)
            state = correction_state(session,key,previous,request)
            if not state["pending"]: raise ConflictError("No unresolved source corrections are recorded")
            if len(state["pending"])>100: raise ConflictError("Correction review exceeds 100 source events; coverage requires review")
            current = {a.source_id:a for a in request.batch.activities}
            changes=[]
            for source in state["pending"]:
                if source not in current:
                    raise ConflictError("Refresh the affected source interval before reviewing this correction")
                choices=state["variants"][source]
                chosen=next((digest for digest,activity in choices.items() if _economic_hash(activity)==_economic_hash(current[source])),None)
                if chosen is None: raise ConflictError("Latest source version has not been retained")
                changes.append({"source_id":source,"previous_hash":state["selected"][source],"selected_hash":chosen,
                    "seen_hashes":sorted(choices),"previous_activity":choices[state["selected"][source]].model_dump(mode="json"),
                    "selected_activity":choices[chosen].model_dump(mode="json")})
            selected,errors,omitted,ids=correction_selection(session,key,previous,request,changes)
            before=_calculate_report(session,key,baseline,previous,request,state["activities"],[],set(),ids)
            after=_calculate_report(session,key,baseline,previous,request,selected,errors,set(),ids)
            # Only an old mark which reconciles under the previously selected
            # source set and conflicts under the correction may be excluded.
            # Unrelated existing discrepancies cannot be waived by this review.
            bad_before={item.get("at") for item in before["discrepancies"] if item.get("at")}
            bad_before.update(item["detail"] for item in before["discrepancies"] if item["code"]=="conflicting_account_snapshot")
            bad_after={item["at"] for item in after["discrepancies"] if item.get("at")}
            changed_marks={item["at"] for item in after["discrepancies"]
                if item.get("at") and item["code"] in {"cash_mismatch","position_mismatch"} and item["at"] not in bad_before}
            newly_omitted=[row for row in previous if row.observed_at<latest.observed_at and row.observed_at.isoformat() in changed_marks
                           and row.reconciliation_id not in omitted]
            restored=[row.reconciliation_id for row in previous if row.reconciliation_id in omitted and row.observed_at.isoformat() not in bad_after]
            omitted=(omitted-set(restored))|{row.reconciliation_id for row in newly_omitted}
            after=_calculate_report(session,key,baseline,previous,request,selected,errors,omitted,ids)
            payload={"account_key":key,"reconciliation_id":latest.reconciliation_id,"calculation_build":_ACCOUNTING_BUILD,
                "changes":changes,"excluded_observation_ids":sorted(omitted),
                "restored_observation_ids":sorted(restored),
                "newly_excluded_observations":[{"reconciliation_id":row.reconciliation_id,"observed_at":row.observed_at.isoformat(),
                    "cash_usd":row.request["snapshot"]["cash_usd"],"equity_usd":row.request["snapshot"]["equity_usd"]} for row in newly_omitted],
                "before":_review_metrics(before),"after":_review_metrics(after),"eligible":after["reconciled"],
                "discrepancies":after["discrepancies"],"limitations":after["limitations"],
                "effect":"Select the displayed observed versions for future calculations. Original activities and reports remain immutable. Reconcile again after approval."}
            payload=json.loads(json.dumps(payload,default=_decimal_wire))
            review=PaperCorrectionReviewRecord(account_key=key,content_hash=content_hash(payload),state_hash=state["state_hash"],payload=payload,expires_at=now_utc()+timedelta(minutes=5))
            session.add(review)
        return review

    def approve_corrections(self,key,review_id,expected_hash,actor,reason):
        if not actor.strip() or not reason.strip(): raise ValueError("Correction approval requires a named actor and reason")
        with self.transaction() as session:
            review=require(session,PaperCorrectionReviewRecord,review_id)
            if review.account_key!=key or review.content_hash!=expected_hash or content_hash(review.payload)!=expected_hash:
                raise ConflictError("Correction approval does not match this account's displayed review")
            existing=session.exec(select(PaperCorrectionApprovalRecord).where(PaperCorrectionApprovalRecord.review_id==review_id)).first()
            if existing:return existing
            previous=list(session.exec(select(PaperReconciliationRecord).options(defer(PaperReconciliationRecord.report, raiseload=True)).where(PaperReconciliationRecord.account_key==key)))
            state=correction_state(session,key,previous)
            if review.expires_at<=now_utc() or state["state_hash"]!=review.state_hash or review.payload["calculation_build"]!=_ACCOUNTING_BUILD:
                raise ConflictError("Account or correction evidence changed; prepare a fresh correction review")
            if not review.payload["eligible"]: raise ConflictError("Displayed correction still has unresolved discrepancies")
            record=PaperCorrectionApprovalRecord(review_id=review_id,account_key=key,actor=actor,reason=reason)
            session.add(record)
            session.add(ApprovalLedgerRecord(room_id="transactions",source="paper_accounting",entity_type="paper_source_correction",entity_id=review_id,
                action="accept",actor=actor,summary=reason,payload={"account_key":key,"review_hash":expected_hash,"state_hash":review.state_hash}))
        return record

    def correction_coverage_start(self,key):
        with self.sessions() as session:
            previous=list(session.exec(select(PaperReconciliationRecord).options(defer(PaperReconciliationRecord.report, raiseload=True)).where(PaperReconciliationRecord.account_key==key)))
            state=correction_state(session,key,previous)
            dates=[activity.effective_at for source in state["pending"] for activity in state["variants"][source].values()]
            return min(dates)-timedelta(microseconds=1) if dates else None


def _calculate_report(session, key, baseline_row, previous, request, selected_activities, correction_errors, omitted, correction_ids):
    baseline = PaperAccountSnapshot.model_validate(baseline_row.snapshot)
    errors = list(correction_errors)
    intervals = [(old.request["batch"]["coverage_start"], old.request["batch"]["coverage_end"])
        for old in previous if old.request["batch"]["complete"]]
    intervals = [(datetime.fromisoformat(start), datetime.fromisoformat(end)) for start,end in intervals]
    if request.batch.complete: intervals.append((request.batch.coverage_start, request.batch.coverage_end))
    covered_until = baseline.observed_at
    for start,end in sorted(intervals):
        if start > covered_until: break
        covered_until = max(covered_until, end)
    if covered_until < request.snapshot.observed_at or not request.batch.complete:
        errors.append({"code":"activity_coverage_gap", "detail":"Continuous activity coverage since the reviewed baseline is required"})
    activities = []
    for item in selected_activities:
        if item.effective_at <= baseline.observed_at:
            # No activity may be silently applied on top of an opening
            # balance that may already contain it.
            errors.append({"code":"activity_precedes_baseline", "source_id":item.source_id})
        elif item.effective_at <= request.snapshot.observed_at: activities.append(item)
        else: errors.append({"code":"activity_after_snapshot", "source_id":item.source_id})
    snapshot_map = {}
    for row in previous:
        if row.reconciliation_id in omitted: continue
        old = PaperAccountSnapshot.model_validate(row.request["snapshot"])
        if old.observed_at in snapshot_map and snapshot_map[old.observed_at] != old:
            errors.append({"code":"conflicting_account_snapshot", "detail":old.observed_at.isoformat()})
        snapshot_map[old.observed_at] = old
    if request.snapshot.observed_at in snapshot_map and snapshot_map[request.snapshot.observed_at] != request.snapshot:
        errors.append({"code":"conflicting_account_snapshot", "detail":request.snapshot.observed_at.isoformat()})
    snapshot_map[request.snapshot.observed_at] = request.snapshot
    attempts = list(session.exec(select(PaperExecutionAttemptRecord).where(PaperExecutionAttemptRecord.account_key == key)))
    orders = {attempt.order_id: require(session, ExactPaperOrderRecord, attempt.order_id) for attempt in attempts}
    attribution, links, protections, lineage_errors = protection_lineage(attempts, orders, previous, request)
    from tradingagents.scheduling.models import ScheduledLeg
    scheduled = {leg.order_id:leg.schedule_id for leg in session.exec(select(ScheduledLeg)) if leg.order_id in orders}
    for attempt in attempts:
        if attempt.order_id in scheduled and attempt.broker_order_id:
            attribution[attempt.broker_order_id] = f"schedule:{scheduled[attempt.order_id]}"
    errors.extend(lineage_errors)
    errors.extend(apply_fill_lineage(activities, links))
    report = reconcile_account(baseline, list(snapshot_map.values()), activities, attribution)
    report["protective_orders"] = protections
    report["protective_lineage"] = list(links.values())
    for fill in report["fills"]:
        if fill["broker_order_id"] in links:
            link = links[fill["broker_order_id"]]
            fill.update(parent_broker_order_id=link["parent_broker_order_id"], protection_role=link["protection_role"])
    report["discrepancies"].extend(errors)
    report["limitations"].extend(request.batch.limitations)
    if errors: _invalidate(report)
    report["evidence_kind"] = request.snapshot.evidence_kind
    report["baseline_id"] = baseline_row.baseline_id
    report["account_key"] = key
    report["calculation_method"] = "fifo_unitized_owner_cash_v2"
    report["calculation_build"] = _ACCOUNTING_BUILD
    report["activity_count"] = len(selected_activities)
    report["open_orders"] = [order.model_dump(mode="json") for order in request.snapshot.open_orders]
    report["outstanding_execution"] = []
    for attempt in attempts:
        if attempt.state in {"filled", "canceled", "expired", "rejected"}: continue
        order = require(session, ExactPaperOrderRecord, attempt.order_id)
        report["outstanding_execution"].append({"intent_id":order.intent_id, "state":order.state,
            "broker_order_id":attempt.broker_order_id, "failure_reason":attempt.failure_reason})
    report["source_corrections"] = {"approval_ids":correction_ids,"excluded_observation_ids":sorted(omitted),"method":"Reviewed observed source versions; original receipts remain immutable"}
    if omitted: report["limitations"].append("Reviewed source corrections exclude affected historical balance observations from this calculation. Their original receipts remain available; replacement historical valuations and unobserved drawdown peaks are not inferred.")
    return report


def _decimal_wire(value):
    if isinstance(value, Decimal): return str(value)
    raise TypeError(f"Unsupported accounting wire value: {type(value).__name__}")


def _review_metrics(report):
    return {field:report[field] for field in ("reconciled","equity_usd","cash_usd","investment_pnl_usd",
        "time_weighted_return_fraction","drawdown_fraction","maximum_drawdown_fraction","realized_pnl_usd","fees_usd","net_external_flows_usd")}


def _economic_hash(activity):
    # Complete native payloads remain in every batch receipt. Formatting or
    # retrieval metadata changes alone do not restate an economic event.
    def normalized(value):
        if isinstance(value, Decimal): return format(value.normalize(), "f")
        if isinstance(value, datetime): return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, dict): return {key:normalized(item) for key,item in value.items()}
        if isinstance(value, list): return [normalized(item) for item in value]
        return value
    return content_hash(normalized(activity.model_dump(exclude={"raw"} if activity.kind != "unknown" else set())))


def _invalidate(report):
    report["reconciled"] = False
    if report["investment_pnl_usd"] is not None:
        report["unexplained_equity_change_usd"] = report["investment_pnl_usd"]
    report["investment_pnl_usd"] = None
    for field in ("time_weighted_return_fraction", "drawdown_fraction", "maximum_drawdown_fraction"):
        report[field] = None
    for point in report["equity_history"]:
        point["time_weighted_return_fraction"] = point["drawdown_fraction"] = point["investment_pnl_usd"] = None


def _fresh(snapshot):
    now = now_utc()
    if snapshot.equity_usd <= 0:
        raise ConflictError("An observation baseline requires positive opening equity")
    if not snapshot.complete or snapshot.started_at < now-timedelta(seconds=15) or snapshot.observed_at > now+timedelta(seconds=1):
        raise ConflictError("Baseline needs a fresh, complete account snapshot")
    if not equity_reconciles(snapshot):
        raise ConflictError("Baseline cash and marked holdings do not reconcile to equity")


def install_accounting_guards(engine):
    with engine.begin() as connection:
        for table in ("paper_account_enrollments", "paper_account_activities", "paper_activity_revisions", "paper_account_reconciliations", "paper_correction_reviews", "paper_correction_approvals"):
            for action in ("UPDATE", "DELETE"):
                connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'paper accounting evidence is immutable'); END"))
        condition = " OR ".join(f'OLD."{field}" IS NOT NEW."{field}"' for field in ("account_key", "content_hash", "snapshot", "expires_at", "created_at"))
        connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS paper_baseline_pin BEFORE UPDATE ON paper_account_baselines WHEN {condition} BEGIN SELECT RAISE(ABORT, 'paper baseline is immutable'); END"))
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS paper_baseline_no_delete BEFORE DELETE ON paper_account_baselines BEGIN SELECT RAISE(ABORT, 'paper baseline history is immutable'); END"))
