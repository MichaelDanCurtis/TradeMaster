"""Read-only briefing from durable research/accounting records; no dispatch."""
from decimal import Decimal

from sqlalchemy import func
from sqlmodel import select

from tradingagents.research.accounting_models import PaperEnrollmentRecord, PaperReconciliationRecord
from tradingagents.research.deployment_models import StrategyDeploymentRecord
from tradingagents.research.models import ExperimentRecord, ResearchFamilyRecord, StrategyRecord, DatasetSnapshotRecord
from tradingagents.research.repository import family_usage
from tradingagents.ui.models import now_utc


def research_overview(sessions, *, limit=20):
    if not 1 <= limit <= 50:
        raise ValueError("Overview limit must be between one and fifty")
    with sessions() as session:
        def count(model):
            return session.exec(select(func.count()).select_from(model)).one()

        states = dict(session.exec(select(ExperimentRecord.state, func.count())
            .group_by(ExperimentRecord.state)).all())
        runs = session.exec(select(ExperimentRecord, StrategyRecord.name, DatasetSnapshotRecord.evidence_kind)
            .join(StrategyRecord, StrategyRecord.strategy_id == ExperimentRecord.strategy_id)
            .join(DatasetSnapshotRecord, DatasetSnapshotRecord.snapshot_id == ExperimentRecord.snapshot_id)
            .order_by(func.coalesce(ExperimentRecord.ended_at, ExperimentRecord.created_at).desc(),
                ExperimentRecord.experiment_id.desc()).limit(limit)).all()
        experiments = []
        for run, name, kind in runs:
            result = run.result or {}
            gaps = set()
            for assessment in result.get("report", {}).get("assessments", []):
                for check in assessment.get("checks", []):
                    if check.get("passed") is False and check.get("name") in {
                        "known_availability", "observations", "coverage", "event_clusters", "human_labels", "prospective_classifier"}:
                        gaps.add(check["name"])
            experiments.append({"experiment_id": run.experiment_id, "strategy_id": run.strategy_id, "name": name,
                "state": run.state, "evidence_kind": kind, "evidence_status": result.get("evidence_status"),
                "updated_at": run.ended_at or run.created_at, "data_gaps": sorted(gaps),
                "message": (result.get("explanation") or run.failure_reason or
                    ("Waiting for a research worker" if run.state == "queued" else "Inspect the saved experiment"))[:1200]})
        pending_states = ("paused", "failed", "paper_review")
        deployment_total = session.exec(select(func.count()).select_from(StrategyDeploymentRecord)
            .where(StrategyDeploymentRecord.state.in_(pending_states))).one()
        deployments = session.exec(select(StrategyDeploymentRecord).where(StrategyDeploymentRecord.state.in_(pending_states))
            .order_by(StrategyDeploymentRecord.updated_at.desc(), StrategyDeploymentRecord.deployment_id).limit(limit)).all()
        families = session.exec(select(ResearchFamilyRecord, StrategyRecord.name).join(StrategyRecord,
            StrategyRecord.strategy_id == ResearchFamilyRecord.strategy_id)
            .order_by(StrategyRecord.updated_at.desc(), ResearchFamilyRecord.family_id).limit(limit)).all()
        budgets = []
        for family, name in families:
            trials, cost = family_usage(session, family.family_id)
            maximum = Decimal(family.compute_budget_usd)
            budgets.append({"family_id": family.family_id, "strategy_id": family.strategy_id, "name": name,
                "trials_used": trials, "max_trials": family.max_trials, "charged_cost_usd": str(cost),
                "budget_usd": str(maximum), "remaining_usd": str(max(Decimal(0), maximum - cost)),
                "exhausted": trials >= family.max_trials or cost >= maximum})
        accounts = []
        enrollments = session.exec(select(PaperEnrollmentRecord).order_by(PaperEnrollmentRecord.approved_at.desc(),
            PaperEnrollmentRecord.account_key).limit(limit)).all()
        for enrollment in enrollments:
            latest = session.exec(select(PaperReconciliationRecord).where(PaperReconciliationRecord.account_key == enrollment.account_key)
                .order_by(PaperReconciliationRecord.created_at.desc(), PaperReconciliationRecord.reconciliation_id.desc()).limit(1)).first()
            report = latest.report if latest else {}
            state = "not_observed" if latest is None else "discrepancy" if not report.get("reconciled") else (
                "drawdown_unavailable" if report.get("drawdown_fraction") is None else "reconciled")
            accounts.append({"account_id": enrollment.account_id, "provider_id": enrollment.provider_id,
                "state": state, "observed_at": latest.observed_at if latest else None,
                "evidence_kind": latest.request.get("snapshot", {}).get("evidence_kind") if latest else None,
                "discrepancies": len(report.get("discrepancies", [])) if latest else None})
        return {"as_of": now_utc(), "experiment_states": states, "experiments": experiments,
            "deployments": [{"deployment_id": row.deployment_id, "name": row.name, "state": row.state,
                "has_committed_funding": row.active_terms_id is not None, "updated_at": row.updated_at} for row in deployments],
            "budgets": budgets, "accounts": accounts,
            "totals": {"experiments": sum(states.values()), "deployments_needing_review": deployment_total,
                "families": count(ResearchFamilyRecord), "accounts": count(PaperEnrollmentRecord)},
            "limit": limit,
            "data_capabilities": [
                {"name": "Immutable dataset imports", "status": "available", "detail": "Structure and artifact integrity checked; provider provenance and data-use rights remain declared."},
                {"name": "Alpaca source capture", "status": "operator_cli", "detail": "Raw bars, calendar and corporate actions can be captured explicitly. Normalization stays under review; automatic dataset admission is unavailable."},
                {"name": "Provider coverage and entitlements", "status": "unverified", "detail": "This status read makes no provider request and verifies no account entitlement."}]}
