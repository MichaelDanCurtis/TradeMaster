"""Local deployment supervisor heartbeats; provider readiness stays separate."""
from datetime import timedelta
import hashlib
from pathlib import Path

from sqlmodel import select

from tradingagents.research.contracts import content_hash
from tradingagents.research.deployment_models import DeploymentWorkerRecord, DeploymentEvaluationJob
from tradingagents.research.repository import ResearchRepository, ConflictError, require
from tradingagents.ui.models import now_utc

HEARTBEAT_SECONDS = 5
STALE_SECONDS = 20


def worker_build():
    return content_hash({name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("deployment_worker.py", "deployment_supervisor.py", "deployment_cycle_child.py", "deployment_health.py")})


class DeploymentHealth(ResearchRepository):
    def register(self, worker_id, *, mode, interval_seconds, cycle_timeout_seconds):
        if mode not in {"evaluate", "reconcile_only"} or not 5 <= interval_seconds <= 300 or not 10 <= cycle_timeout_seconds <= 600:
            raise ValueError("Invalid deployment supervisor limits")
        with self.transaction() as session:
            if session.get(DeploymentWorkerRecord, worker_id):
                raise ConflictError("Worker IDs are unique to a supervisor process")
            session.add(DeploymentWorkerRecord(worker_id=worker_id, mode=mode, build_hash=worker_build(),
                interval_seconds=interval_seconds, cycle_timeout_seconds=cycle_timeout_seconds))

    def heartbeat(self, worker_id):
        with self.transaction() as session:
            worker = require(session, DeploymentWorkerRecord, worker_id)
            if worker.phase == "stopped":
                raise ConflictError("Stopped supervisor cannot resume its heartbeat")
            worker.last_seen_at = now_utc()
            session.add(worker)

    def start_cycle(self, worker_id, cycle_id):
        with self.transaction() as session:
            worker = require(session, DeploymentWorkerRecord, worker_id)
            if worker.phase == "stopped" or worker.cycle_id:
                raise ConflictError("Supervisor already stopped or has a cycle in progress")
            worker.cycle_id, worker.job_id, worker.phase = cycle_id, None, "observing"
            worker.account_key = None  # Never claim a previous provider selection is current.
            worker.cycle_deadline = now_utc() + timedelta(seconds=worker.cycle_timeout_seconds)
            worker.last_seen_at = now_utc()
            session.add(worker)
            return worker

    def progress(self, worker_id, cycle_id, phase, *, account_key=None, job_id=None):
        if phase not in {"observing", "evaluating", "canceling"}:
            raise ValueError("Invalid cycle phase")
        with self.transaction() as session:
            worker = require(session, DeploymentWorkerRecord, worker_id)
            if worker.cycle_id != cycle_id or not worker.cycle_deadline or now_utc() >= worker.cycle_deadline:
                raise ConflictError("Cycle no longer belongs to this supervisor")
            worker.phase, worker.account_key, worker.job_id = phase, account_key, job_id
            session.add(worker)  # Only the supervisor updates last_seen_at.

    def finish_cycle(self, worker_id, cycle_id, result):
        with self.transaction() as session:
            worker = require(session, DeploymentWorkerRecord, worker_id)
            if worker.cycle_id != cycle_id:
                raise ConflictError("Cycle completion belongs to another supervisor cycle")
            worker.phase = "idle" if result.get("status") in {"reconciled", "baseline_review_required"} else "attention"
            worker.last_result = {key: result[key] for key in ("status", "error_type", "account", "job", "message") if key in result}
            worker.cycle_id, worker.cycle_deadline, worker.job_id = None, None, None
            worker.last_seen_at = now_utc()
            session.add(worker)

    def stop(self, worker_id):
        with self.transaction() as session:
            worker = require(session, DeploymentWorkerRecord, worker_id)
            worker.phase, worker.cycle_id, worker.cycle_deadline, worker.job_id = "stopped", None, None, None
            worker.last_seen_at = now_utc()
            session.add(worker)

    def runtime(self, account_key=None):
        with self.sessions() as session:
            query = select(DeploymentWorkerRecord)
            if account_key:
                query = query.where(DeploymentWorkerRecord.account_key == account_key)
            rows = list(session.exec(query.order_by(DeploymentWorkerRecord.last_seen_at.desc()).limit(25)))
            pending = select(DeploymentEvaluationJob).where(DeploymentEvaluationJob.state.in_(["queued", "running"]))
            if account_key:
                pending = pending.where(DeploymentEvaluationJob.account_key == account_key)
            jobs = list(session.exec(pending))
            now = now_utc()
            workers = []
            for row in rows:
                age = (now-row.last_seen_at).total_seconds()
                connected = 0 <= age < STALE_SECONDS and row.phase != "stopped" and (row.cycle_deadline is None or now < row.cycle_deadline)
                workers.append({**row.model_dump(mode="json"), "connected": connected,
                    "heartbeat_age_seconds": max(0, age), "status": row.phase if connected or row.phase == "stopped" else "stale"})
            connected = any(row["connected"] for row in workers)
            evaluating = any(row["connected"] and row["mode"] == "evaluate" for row in workers)
            return {"connected": connected, "evaluation_worker_connected": evaluating, "workers": workers,
                "queued": sum(job.state == "queued" for job in jobs), "running": sum(job.state == "running" for job in jobs),
                "stale_after_seconds": STALE_SECONDS,
                "message": "Evaluation worker heartbeat received. Account reconciliation and job eligibility are checked separately." if evaluating else
                    "An account observer is connected in reconciliation-only mode; it will not consume queued evaluations." if connected else
                    "No recent matching worker heartbeat. Queued evaluations wait for a deployment worker.",
                "order_authority": False}
