"""Transactional research persistence and bounded job lifecycle."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from decimal import Decimal
from typing import Iterator, TypeVar

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel, select

from tradingagents.research.contracts import (
    ExperimentInput, ExperimentResult, FreezeVersion, ResearchPlanInput,
    SnapshotManifest, StrategyDraft, StrategySpec, content_hash,
)
from tradingagents.research.models import (
    DatasetSnapshotRecord, ExperimentEventRecord, ExperimentRecord,
    HoldoutUseRecord, ResearchFamilyRecord, ResearchPlanRecord,
    StrategyRecord, StrategyVersionRecord,
    ResearchWorkerRecord,
    ResearchModelCallRecord,
    StrategyDesignRecord,
)
from tradingagents.ui.models import now_utc


class ConflictError(ValueError):
    pass


class MissingRecordError(LookupError):
    pass


Record = TypeVar("Record", bound=SQLModel)


def require(session: Session, cls: type[Record], identifier: str) -> Record:
    record = session.get(cls, identifier)
    if record is None:
        raise MissingRecordError(f"{cls.__name__} not found: {identifier}")
    return record


def family_usage(session: Session, family_id: str) -> tuple[int, Decimal]:
    experiments = list(session.exec(select(ExperimentRecord).where(ExperimentRecord.family_id == family_id)))
    designs = list(session.exec(select(StrategyDesignRecord).where(StrategyDesignRecord.family_id == family_id)))
    return (sum(row.trial_count for row in experiments) + len(designs),
            sum((Decimal(row.cost_usd) for row in experiments), Decimal(0)) +
            sum((Decimal(row.charged_cost_usd) for row in designs), Decimal(0)))


class ResearchRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self.sessions = session_factory

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.sessions() as session:
            # Serialize check-and-write transactions across local workers/API calls.
            # Research's initial storage contract is SQLite; no locks are implied
            # for a different backend until its transaction adapter is implemented.
            if session.get_bind().dialect.name != "sqlite":
                raise RuntimeError("research transactions currently require SQLite")
            session.execute(text("BEGIN IMMEDIATE"))
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def create_strategy(self, draft: StrategyDraft) -> StrategyRecord:
        with self.transaction() as session:
            record = StrategyRecord(**draft.model_dump())
            session.add(record)
        return record

    def revise_draft(self, strategy_id: str, draft: StrategyDraft, expected_revision: int) -> StrategyRecord:
        with self.transaction() as session:
            record = require(session, StrategyRecord, strategy_id)
            if record.revision != expected_revision:
                raise ConflictError("draft changed; reload before saving")
            for key, value in draft.model_dump().items():
                setattr(record, key, value)
            record.revision += 1
            record.updated_at = now_utc()
            session.add(record)
        return record

    def list_strategies(self) -> list[StrategyRecord]:
        with self.sessions() as session:
            return list(session.exec(select(StrategyRecord).order_by(StrategyRecord.created_at.desc())))

    def strategy(self, strategy_id: str) -> dict:
        with self.sessions() as session:
            record = require(session, StrategyRecord, strategy_id)
            versions = list(session.exec(select(StrategyVersionRecord).where(StrategyVersionRecord.strategy_id == strategy_id).order_by(StrategyVersionRecord.created_at)))
            plans = list(session.exec(select(ResearchPlanRecord).where(ResearchPlanRecord.strategy_id == strategy_id).order_by(ResearchPlanRecord.created_at)))
            family = session.exec(select(ResearchFamilyRecord).where(ResearchFamilyRecord.strategy_id == strategy_id)).first()
            usage = family_usage(session, family.family_id) if family else (0, Decimal(0))
            return {"strategy": record, "versions": versions, "plans": plans, "family": family,
                    "family_usage": {"trials": usage[0], "cost_usd": str(usage[1])}}

    def freeze_version(self, strategy_id: str, request: FreezeVersion) -> StrategyVersionRecord:
        return self.freeze_versions(strategy_id, [request])[0]

    def freeze_versions(self, strategy_id: str, requests: list[FreezeVersion]) -> list[StrategyVersionRecord]:
        if not 1 <= len(requests) <= 12:
            raise ValueError("Freeze between one and twelve versions per transaction")
        with self.transaction() as session:
            strategy = require(session, StrategyRecord, strategy_id)
            records = []
            for request in requests:
                if request.parent_version_id:
                    parent = require(session, StrategyVersionRecord, request.parent_version_id)
                    if parent.strategy_id != strategy_id:
                        raise ConflictError("parent belongs to another strategy")
                payload = {
                    "spec": request.spec.model_dump(mode="json"),
                    "hypothesis": strategy.hypothesis, "rationale": strategy.rationale,
                    "draft_revision": strategy.revision, "parent_version_id": request.parent_version_id,
                }
                if request.design_id:
                    design = require(session, StrategyDesignRecord, request.design_id)
                    if design.strategy_id != strategy_id or design.state != "completed" or not design.receipt or not design.receipt.get("proposal") or design.receipt["proposal"]["status"] != "supported":
                        raise ConflictError("Version provenance requires a valid supported design for this strategy")
                    payload["design_id"] = design.design_id
                    payload["design_request_hash"] = design.request_hash
                digest = content_hash(payload)
                record = session.exec(select(StrategyVersionRecord).where(StrategyVersionRecord.strategy_id == strategy_id, StrategyVersionRecord.content_hash == digest)).first()
                if record is None:
                    record = StrategyVersionRecord(strategy_id=strategy_id, parent_version_id=request.parent_version_id, content_hash=digest, payload=payload)
                    session.add(record)
                    session.flush()
                records.append(record)
        return records

    def freeze_plan(self, request: ResearchPlanInput) -> ResearchPlanRecord:
        with self.transaction() as session:
            require(session, StrategyRecord, request.strategy_id)
            families = list(session.exec(select(ResearchFamilyRecord).where(ResearchFamilyRecord.strategy_id == request.strategy_id)))
            if families and families[0].family_id != request.family_id:
                raise ConflictError("strategy revisions must keep the existing research family")
            family = session.get(ResearchFamilyRecord, request.family_id)
            if family:
                if family.strategy_id != request.strategy_id:
                    raise ConflictError("family belongs to another strategy")
                if family.max_trials != request.max_trials or Decimal(family.compute_budget_usd) != request.compute_budget_usd:
                    raise ConflictError("a new plan cannot reset the family's frozen trial or cost budget")
            else:
                session.add(ResearchFamilyRecord(family_id=request.family_id, strategy_id=request.strategy_id, max_trials=request.max_trials, compute_budget_usd=str(request.compute_budget_usd)))
                session.flush()
            specs = {}
            for vid in request.version_ids:
                version = require(session, StrategyVersionRecord, vid)
                if version.strategy_id != request.strategy_id:
                    raise ConflictError("all variants must belong to this strategy")
                specs[vid] = StrategySpec.model_validate(version.payload["spec"])
            from tradingagents.research.evaluation.cohorts import guidance_cohorts
            guidance_cohorts(specs)
            if request.extraction and (not any(s.model for s in specs.values()) or any(s.model and not s.model.provider_config_hash for s in specs.values())):
                raise ValueError("New extraction calls require a pinned provider configuration for each challenger")
            digest = content_hash(request)
            record = session.exec(select(ResearchPlanRecord).where(ResearchPlanRecord.content_hash == digest)).first()
            if record is None:
                record = ResearchPlanRecord(strategy_id=request.strategy_id, family_id=request.family_id, content_hash=digest, payload=request.model_dump(mode="json"))
                session.add(record)
        return record

    def register_snapshot(self, manifest: SnapshotManifest) -> DatasetSnapshotRecord:
        with self.transaction() as session:
            digest = content_hash(manifest)
            record = session.exec(select(DatasetSnapshotRecord).where(DatasetSnapshotRecord.content_hash == digest)).first()
            if record is None:
                record = DatasetSnapshotRecord(content_hash=digest, evidence_kind=manifest.evidence_kind, payload=manifest.model_dump(mode="json"))
                session.add(record)
        return record

    def list_snapshots(self) -> list[DatasetSnapshotRecord]:
        with self.sessions() as session:
            return list(session.exec(select(DatasetSnapshotRecord).order_by(DatasetSnapshotRecord.created_at.desc())))

    def queue_experiment(self, request: ExperimentInput) -> ExperimentRecord:
        with self.transaction() as session:
            digest = content_hash(request)
            existing = session.exec(select(ExperimentRecord).where(ExperimentRecord.idempotency_key == request.idempotency_key)).first()
            if existing:
                if existing.request_hash != digest:
                    raise ConflictError("idempotency key already used with different inputs")
                return existing
            plan_record = require(session, ResearchPlanRecord, request.plan_id)
            plan = ResearchPlanInput.model_validate(plan_record.payload)
            snapshot = require(session, DatasetSnapshotRecord, request.snapshot_id)
            manifest = SnapshotManifest.model_validate(snapshot.payload)
            if plan.equity_reference and plan.equity_reference.instrument.instrument_id not in manifest.instrument_ids:
                raise ConflictError("snapshot does not cover the predeclared equity reference")
            # A run cannot silently omit instruments because a provider lacks them.
            for vid in plan.version_ids:
                spec = StrategySpec.model_validate(require(session, StrategyVersionRecord, vid).payload["spec"])
                if not {i.instrument_id for i in spec.universe}.issubset(manifest.instrument_ids):
                    raise ConflictError("snapshot does not cover the strategy universe")
            stage_start = {"development": plan.split.train_start, "validation": plan.split.validation_start, "holdout": plan.split.holdout_start}[request.evaluation]
            stage_end = {"development": plan.split.train_end, "validation": plan.split.validation_end, "holdout": plan.split.holdout_end}[request.evaluation]
            if manifest.coverage_start > stage_start or manifest.coverage_end < stage_end:
                raise ConflictError("snapshot does not cover the evaluation period")
            if manifest.availability == "unverified" and request.evaluation != "development":
                raise ConflictError("unverified availability is restricted to exploratory development")
            family = require(session, ResearchFamilyRecord, plan.family_id)
            used_trials, used_cost = family_usage(session, plan.family_id)
            trial_count = len(plan.version_ids) * len(plan.scenarios)
            if used_trials + trial_count > family.max_trials:
                raise ConflictError("research family trial budget exhausted")
            if used_cost >= Decimal(family.compute_budget_usd):
                raise ConflictError("research family cost budget exhausted")
            active = list(session.exec(select(ExperimentRecord).where(ExperimentRecord.state.in_(["queued", "running"]))))
            if len(active) >= 100:
                raise ConflictError("research queue capacity reached")
            if request.parent_experiment_id:
                parent = require(session, ExperimentRecord, request.parent_experiment_id)
                if parent.family_id != plan.family_id:
                    raise ConflictError("retry/revision must remain in its research family")
            if request.evaluation == "holdout":
                for used in session.exec(select(HoldoutUseRecord).where(HoldoutUseRecord.family_id == plan.family_id)):
                    if str(stage_start) <= used.end_date and str(stage_end) >= used.start_date:
                        raise ConflictError("holdout already consumed by this family; choose an unseen period")
            record = ExperimentRecord(plan_id=plan_record.plan_id, strategy_id=plan.strategy_id, family_id=plan.family_id, snapshot_id=snapshot.snapshot_id, parent_experiment_id=request.parent_experiment_id, idempotency_key=request.idempotency_key, request_hash=digest, evaluation=request.evaluation, engine=request.engine, trial_count=trial_count)
            session.add(record)
            session.flush()
            # Reserve at dispatch. Failures cannot be abused to peek then reuse.
            if request.evaluation == "holdout":
                session.add(HoldoutUseRecord(family_id=plan.family_id, experiment_id=record.experiment_id, start_date=str(stage_start), end_date=str(stage_end)))
            self._event(session, record.experiment_id, "queued", "Experiment registered before dispatch")
        return record

    def experiment(self, experiment_id: str) -> ExperimentRecord:
        with self.sessions() as session:
            return require(session, ExperimentRecord, experiment_id)

    def experiments(self, strategy_id: str) -> list[ExperimentRecord]:
        with self.sessions() as session:
            require(session, StrategyRecord, strategy_id)
            return list(session.exec(select(ExperimentRecord).where(ExperimentRecord.strategy_id == strategy_id).order_by(ExperimentRecord.created_at.desc())))

    def events(self, experiment_id: str) -> list[ExperimentEventRecord]:
        with self.sessions() as session:
            require(session, ExperimentRecord, experiment_id)
            return list(session.exec(select(ExperimentEventRecord).where(ExperimentEventRecord.experiment_id == experiment_id).order_by(ExperimentEventRecord.created_at)))

    def claim(self, worker_id: str, lease_seconds: int = 60) -> ExperimentRecord | None:
        if not worker_id.strip() or not 1 <= lease_seconds <= 3600:
            raise ValueError("worker identity and bounded lease required")
        with self.transaction() as session:
            now = now_utc()
            records = list(session.exec(select(ExperimentRecord).where(ExperimentRecord.state.in_(["queued", "running"])).order_by(ExperimentRecord.created_at)))
            for record in records:
                if record.state == "running" and record.lease_until is not None and record.lease_until > now:
                    continue
                if record.attempts >= 3:
                    record.state, record.failure_reason, record.ended_at = "failed", "worker lease recovery limit exceeded", now
                    record.lease_owner, record.lease_until = None, None
                    session.add(record)
                    self._event(session, record.experiment_id, "failed", record.failure_reason)
                    continue
                record.state, record.lease_owner = "running", worker_id
                record.lease_until = now + timedelta(seconds=lease_seconds)
                record.started_at = record.started_at or now
                record.attempts += 1
                session.add(record)
                self._event(session, record.experiment_id, "claimed", f"Worker attempt {record.attempts}")
                return record
        return None

    def heartbeat(self, experiment_id: str, worker_id: str, lease_seconds: int = 60) -> None:
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("lease must be bounded")
        with self.transaction() as session:
            record = self._owned(session, experiment_id, worker_id)
            record.lease_until = now_utc() + timedelta(seconds=lease_seconds)
            session.add(record)

    def charge(self, experiment_id: str, worker_id: str, amount: Decimal) -> None:
        """Reserve a metered operation's maximum cost before dispatching it."""
        if not amount.is_finite() or amount < 0:
            raise ValueError("cost must be finite and nonnegative")
        with self.transaction() as session:
            record = self._owned(session, experiment_id, worker_id)
            family = require(session, ResearchFamilyRecord, record.family_id)
            _, total = family_usage(session, record.family_id)
            if total + amount > Decimal(family.compute_budget_usd):
                raise ConflictError("research family cost budget exhausted")
            record.cost_usd = str(Decimal(record.cost_usd) + amount)
            session.add(record)

    def model_calls(self, experiment_id: str) -> list[ResearchModelCallRecord]:
        with self.sessions() as session:
            require(session, ExperimentRecord, experiment_id)
            return list(session.exec(select(ResearchModelCallRecord).where(ResearchModelCallRecord.experiment_id == experiment_id).order_by(ResearchModelCallRecord.created_at)))

    def reserve_model_call(self, experiment_id: str, worker_id: str, *, version_id: str, notice_id: str,
                           input_hash: str, input_as_of, provider_fingerprint: str) -> tuple[ResearchModelCallRecord, bool]:
        with self.transaction() as session:
            experiment = self._owned(session, experiment_id, worker_id)
            plan = ResearchPlanInput.model_validate(require(session, ResearchPlanRecord, experiment.plan_id).payload)
            if plan.extraction is None or version_id not in plan.version_ids:
                raise ConflictError("Model dispatch is not part of this frozen plan")
            spec = StrategySpec.model_validate(require(session, StrategyVersionRecord, version_id).payload["spec"])
            if spec.model is None or spec.model.provider_config_hash != provider_fingerprint:
                raise ConflictError("Model provider configuration does not match the frozen pin")
            request = {"notice_id": notice_id, "input_hash": input_hash, "input_as_of": input_as_of.isoformat(),
                "model": spec.model.model_dump(mode="json"), "policy": plan.extraction.model_dump(mode="json")}
            digest = content_hash(request)
            previous = session.exec(select(ResearchModelCallRecord).where(ResearchModelCallRecord.experiment_id == experiment_id, ResearchModelCallRecord.request_hash == digest)).first()
            if previous is not None:
                return previous, False
            calls = list(session.exec(select(ResearchModelCallRecord).where(ResearchModelCallRecord.experiment_id == experiment_id)))
            if len(calls) >= plan.extraction.max_calls:
                raise ConflictError("Frozen model-call limit exhausted")
            if any(c.failure_reason and "bound" in c.failure_reason for c in calls):
                raise ConflictError("A model call exceeded its frozen bound; dispatch stopped")
            family = require(session, ResearchFamilyRecord, experiment.family_id)
            from tradingagents.research.designer import assert_metering_bounds
            assert_metering_bounds(session, experiment.family_id)
            _, total = family_usage(session, experiment.family_id)
            amount = plan.extraction.maximum_call_cost_usd
            if total + amount > Decimal(family.compute_budget_usd):
                raise ConflictError("Research family cost budget exhausted before model dispatch")
            row = ResearchModelCallRecord(experiment_id=experiment_id, family_id=experiment.family_id, version_id=version_id,
                notice_id=notice_id, input_hash=input_hash, input_as_of=input_as_of, request_hash=digest, request=request,
                provider_fingerprint=provider_fingerprint, worker_id=worker_id, reserved_cost_usd=str(amount), charged_cost_usd=str(amount))
            session.add(row)
            experiment.cost_usd = str(Decimal(experiment.cost_usd)+amount)
            session.add(experiment)
            self._event(session, experiment_id, "model_reserved", "Model call recorded and maximum configured charge reserved before dispatch")
        return row, True

    def dispatch_model_call(self, call_id: str, worker_id: str) -> ResearchModelCallRecord:
        with self.transaction() as session:
            row = require(session, ResearchModelCallRecord, call_id)
            self._owned(session, row.experiment_id, worker_id)
            if row.worker_id != worker_id or row.state != "reserved":
                raise ConflictError("Model call is already dispatched or belongs to another worker")
            row.state, row.dispatched_at = "dispatched", now_utc()
            session.add(row)
        return row

    def complete_model_call(self, call_id: str, worker_id: str, evidence, artifact: str) -> ResearchModelCallRecord:
        from tradingagents.research.data.contracts import EvidenceObservation
        evidence = EvidenceObservation.model_validate(evidence.model_dump())
        with self.transaction() as session:
            row = require(session, ResearchModelCallRecord, call_id)
            if row.worker_id != worker_id or row.state != "dispatched":
                raise ConflictError("Model receipt cannot replace a terminal call or another worker's attempt")
            if (row.notice_id, row.input_hash, row.input_as_of, row.request["model"]) != (evidence.notice_id, evidence.input_hash, evidence.input_as_of, evidence.model.model_dump(mode="json")) or content_hash(evidence) != artifact:
                raise ConflictError("Model receipt differs from the reserved request or artifact")
            # A receipt may settle after cancellation; it never restarts the job.
            experiment = require(session, ExperimentRecord, row.experiment_id)
            actual = evidence.cost_usd
            row.state, row.output_artifact, row.completed_at = "unknown" if evidence.actual_model_id == "unconfirmed" else "completed", artifact, now_utc()
            row.failure_reason = "; ".join(evidence.validation_errors)[:4000] or None
            if actual > Decimal(row.reserved_cost_usd):
                row.failure_reason = "Provider charge exceeded reserved bound; dispatch stopped"
            row.charged_cost_usd = str(actual)
            experiment.cost_usd = str(Decimal(experiment.cost_usd)+actual-Decimal(row.reserved_cost_usd))
            session.add(row)
            session.add(experiment)
            self._event(session, row.experiment_id, "model_completed", "Model receipt and charge preserved; evidence is independently validated")
        return row

    def abandon_model_call(self, call_id: str, worker_id: str, reason: str) -> ResearchModelCallRecord:
        with self.transaction() as session:
            row = require(session, ResearchModelCallRecord, call_id)
            experiment = require(session, ExperimentRecord, row.experiment_id)
            if row.state in {"completed", "unknown"}:
                return row
            if row.worker_id != worker_id:
                self._owned(session, experiment.experiment_id, worker_id)
            row.state, row.completed_at, row.failure_reason = "unknown", now_utc(), reason[:4000]
            session.add(row)
            self._event(session, row.experiment_id, "model_unknown", "Outcome unconfirmed; maximum charge retained and call will not be resubmitted")
        return row

    def finish(self, experiment_id: str, worker_id: str, *, result: ExperimentResult | None = None, failure: str | None = None) -> ExperimentRecord:
        if (result is None) == (failure is None):
            raise ValueError("provide exactly one result or failure")
        with self.transaction() as session:
            record = self._owned(session, experiment_id, worker_id)
            if result and result.operating_cost_usd > Decimal(record.cost_usd):
                raise ConflictError("result cost exceeds precharged budget")
            if result:
                from tradingagents.research.evaluation.comparison import EvidenceReport
                report = EvidenceReport.model_validate(result.report)
                snapshot = require(session, DatasetSnapshotRecord, record.snapshot_id)
                plan = ResearchPlanInput.model_validate(require(session, ResearchPlanRecord, record.plan_id).payload)
                if report.snapshot_kind != snapshot.evidence_kind or result.manifest_hash != snapshot.content_hash or report.snapshot_manifest_hash != snapshot.content_hash:
                    raise ConflictError("result evidence does not match the frozen snapshot")
                if report.engine_build != result.engine_build or report.evaluation != record.evaluation:
                    raise ConflictError("report engine/evaluation differs from the experiment")
                if result.artifacts.get("report") != content_hash(report) or {a.version_id for a in report.assessments} != set(plan.version_ids):
                    raise ConflictError("result report integrity or variant coverage failed")
                controls = {"cash", "fixed_basket", "strategy"} | ({"equity_reference"} if plan.equity_reference else set())
                expected_runs = {(version, scenario.name, control) for version in plan.version_ids for scenario in plan.scenarios for control in controls}
                actual_runs = {(run.version_id, run.scenario, run.control) for run in report.runs}
                if report.equity_reference != plan.equity_reference or actual_runs != expected_runs or len(report.runs) != len(expected_runs):
                    raise ConflictError("report must preserve every frozen control, scenario and equity reference")
                if not {run.artifact_hash for run in report.runs}.issubset(set(result.artifacts.values())):
                    raise ConflictError("report run artifacts are missing")
                from tradingagents.research.evaluation.cohorts import guidance_cohorts
                cohort_specs = {identifier: StrategySpec.model_validate(require(session, StrategyVersionRecord, identifier).payload["spec"])
                                for identifier in plan.version_ids}
                expected_arms = {(cohort[left], cohort[right], scenario.name)
                    for cohort in guidance_cohorts(cohort_specs)
                    for left, right in (("numeric_quality", "guidance_control"), ("astra_challenger", "numeric_quality"))
                    for scenario in plan.scenarios}
                actual_arms = {(arm.challenger_version_id, arm.control_version_id, arm.scenario) for arm in report.arm_comparisons}
                if actual_arms != expected_arms or len(report.arm_comparisons) != len(expected_arms):
                    raise ConflictError("Report must preserve every matched guidance arm and scenario")
                if any(arm.paired_events is None or arm.paired_events.artifact_hash not in result.artifacts.values()
                       or not set(arm.paired_events.page_artifact_hashes).issubset(result.artifacts.values())
                       or not arm.paired_events.reconciled for arm in report.arm_comparisons):
                    raise ConflictError("Paired event accounting artifacts are missing or unreconciled")
                calls = list(session.exec(select(ResearchModelCallRecord).where(ResearchModelCallRecord.experiment_id == experiment_id)))
                if any(c.state not in {"completed", "unknown"} for c in calls) or set(report.model_call_ids) != {c.call_id for c in calls}:
                    raise ConflictError("Report must include every terminal model attempt")
                artifacts = {c.output_artifact for c in calls if c.output_artifact}
                if set(report.evidence_artifacts) != artifacts or not artifacts.issubset(set(result.artifacts.values())):
                    raise ConflictError("Model evidence differs from durable provider receipts")
                costs = {}
                for call in calls:
                    pin = content_hash(call.request["model"])
                    costs[pin] = costs.get(pin, Decimal(0)) + Decimal(call.charged_cost_usd)
                if report.model_call_costs != costs:
                    raise ConflictError("Report model costs differ from the durable charge ledger")
                if artifacts and (not report.evaluated_dataset_hash or result.artifacts.get("evaluated_dataset") != report.evaluated_dataset_hash):
                    raise ConflictError("Model evidence requires a separate immutable evaluated dataset")
                for assessment in report.assessments:
                    if snapshot.evidence_kind == "fixture" and assessment.evidence_status != "fixture_only":
                        raise ConflictError("fixture results cannot become investment evidence")
                    if assessment.evidence_status == "eligible_for_paper_review" and (record.evaluation != "holdout" or not assessment.checks or not all(c.passed for c in assessment.checks)):
                        raise ConflictError("paper-review eligibility requires passing held-out evidence")
                statuses = {a.evidence_status for a in report.assessments}
                expected = next(s for s in ("eligible_for_paper_review", "fixture_only", "insufficient_evidence", "rejected") if s in statuses)
                if result.evidence_status != expected:
                    raise ConflictError("result verdict differs from its version assessments")
            record.state = "completed" if result else "failed"
            record.result = result.model_dump(mode="json") if result else None
            record.failure_reason = failure
            record.ended_at = now_utc()
            record.lease_owner, record.lease_until = None, None
            session.add(record)
            self._event(session, experiment_id, record.state, failure or "Evaluation completed; evidence verdict is separate")
        return record

    def family_trial_count(self, family_id: str) -> int:
        with self.sessions() as session:
            return family_usage(session, family_id)[0]

    def worker_seen(self, worker_id: str, engine_build: str, state: str, experiment_id: str | None = None) -> None:
        with self.transaction() as session:
            row = session.get(ResearchWorkerRecord, worker_id) or ResearchWorkerRecord(worker_id=worker_id, engine_build=engine_build, state=state)
            row.engine_build, row.state, row.experiment_id, row.last_seen_at = engine_build, state, experiment_id, now_utc()
            session.add(row)

    def runtime(self) -> dict:
        with self.sessions() as session:
            rows = list(session.exec(select(ResearchWorkerRecord)))
            active = [r for r in rows if r.last_seen_at > now_utc() - timedelta(seconds=30) and r.state in {"idle", "running"}]
            queued = len(list(session.exec(select(ExperimentRecord).where(ExperimentRecord.state == "queued"))))
            return {"available": bool(active), "workers": active, "queued": queued, "supported_engines": ["local_replay"] if active else [],
                    "message": "Offline replay worker connected" if active else "No recent worker heartbeat. Experiments remain queued until the research worker starts."}

    def cancel(self, experiment_id: str) -> ExperimentRecord:
        with self.transaction() as session:
            record = require(session, ExperimentRecord, experiment_id)
            if record.state in {"completed", "failed", "cancelled"}:
                return record
            record.state, record.ended_at = "cancelled", now_utc()
            record.lease_owner, record.lease_until = None, None
            session.add(record)
            self._event(session, experiment_id, "cancelled", "Cancelled; trial budget and holdout consumption retained")
        return record

    def inputs(self, experiment_id: str) -> tuple[ExperimentRecord, ResearchPlanInput, SnapshotManifest, dict[str, StrategySpec]]:
        with self.sessions() as session:
            run = require(session, ExperimentRecord, experiment_id)
            plan_row = require(session, ResearchPlanRecord, run.plan_id)
            snapshot_row = require(session, DatasetSnapshotRecord, run.snapshot_id)
            if content_hash(plan_row.payload) != plan_row.content_hash or content_hash(snapshot_row.payload) != snapshot_row.content_hash:
                raise ConflictError("immutable research inputs failed integrity check")
            plan = ResearchPlanInput.model_validate(plan_row.payload)
            specs = {}
            for vid in plan.version_ids:
                version = require(session, StrategyVersionRecord, vid)
                if content_hash(version.payload) != version.content_hash:
                    raise ConflictError("strategy version failed integrity check")
                specs[vid] = StrategySpec.model_validate(version.payload["spec"])
            return run, plan, SnapshotManifest.model_validate(snapshot_row.payload), specs

    @staticmethod
    def _owned(session: Session, experiment_id: str, worker_id: str) -> ExperimentRecord:
        record = require(session, ExperimentRecord, experiment_id)
        if record.state != "running" or record.lease_owner != worker_id or record.lease_until is None or record.lease_until <= now_utc():
            raise ConflictError("worker does not own an active lease")
        return record

    @staticmethod
    def _event(session: Session, experiment_id: str, event_type: str, message: str) -> None:
        session.add(ExperimentEventRecord(experiment_id=experiment_id, event_type=event_type, message=message))


def install_immutability_guards(engine) -> None:
    """Protect frozen artifacts even from accidental future ORM update paths."""
    if engine.dialect.name != "sqlite":
        raise RuntimeError("research storage currently requires SQLite")
    tables = ("research_strategy_versions", "research_plans", "research_snapshots", "research_families", "research_holdout_uses", "research_experiment_events")
    with engine.begin() as connection:
        for table in tables:
            for action in ("UPDATE", "DELETE"):
                connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable research artifact'); END"))
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS research_model_calls_no_delete BEFORE DELETE ON research_model_calls BEGIN SELECT RAISE(ABORT, 'model attempt history is immutable'); END"))
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS research_model_calls_terminal BEFORE UPDATE ON research_model_calls WHEN OLD.state IN ('completed', 'unknown') BEGIN SELECT RAISE(ABORT, 'terminal model receipt is immutable'); END"))
        protected = ("experiment_id", "family_id", "version_id", "notice_id", "input_hash", "input_as_of", "request_hash", "request", "provider_fingerprint", "worker_id", "reserved_cost_usd", "created_at")
        condition = " OR ".join(f"OLD.{name} IS NOT NEW.{name}" for name in protected)
        connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS research_model_calls_pin BEFORE UPDATE ON research_model_calls WHEN {condition} BEGIN SELECT RAISE(ABORT, 'model call pin is immutable'); END"))
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS research_strategy_designs_no_delete BEFORE DELETE ON research_strategy_designs BEGIN SELECT RAISE(ABORT, 'design history is immutable'); END"))
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS research_strategy_designs_terminal BEFORE UPDATE ON research_strategy_designs WHEN OLD.state IN ('completed', 'invalid', 'unknown') BEGIN SELECT RAISE(ABORT, 'design receipt is immutable'); END"))
        protected = ("strategy_id", "family_id", "idempotency_key", "request_hash", "request", "reserved_cost_usd", "created_at", "deadline_at")
        condition = " OR ".join(f"OLD.{name} IS NOT NEW.{name}" for name in protected)
        connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS research_strategy_designs_pin BEFORE UPDATE ON research_strategy_designs WHEN {condition} BEGIN SELECT RAISE(ABORT, 'design request is immutable'); END"))
