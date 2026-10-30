"""Durable offline research worker with leases and a killable runtime boundary.

Start explicitly with ``python -m tradingagents.research.worker --database-url
sqlite:////absolute/path/ui.db``. The API never starts work inside a request.
Each attempt runs in a fresh process with no inherited provider credentials.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from tradingagents.research.contracts import ExperimentResult, canonical_json
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.engines.replay import LocalReplayEngine
from tradingagents.research.engines.base import EngineUnavailable
from tradingagents.research.repository import ConflictError, ResearchRepository
from tradingagents.research.worker_child import WorkerInput
from tradingagents.ui.db import create_session_factory, init_db


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
    except ProcessLookupError:
        pass


class ResearchWorker:
    def __init__(self, repository: ResearchRepository, store: ArtifactStore, *, worker_id: str | None = None,
                 attempt_cost_usd: Decimal = Decimal(0), poll_seconds: float = .2):
        if not attempt_cost_usd.is_finite() or attempt_cost_usd < 0 or attempt_cost_usd != attempt_cost_usd.quantize(Decimal(".000001")):
            raise ValueError("attempt cost must be finite, nonnegative USD with at most six decimal places")
        if not .01 <= poll_seconds <= 5:
            raise ValueError("worker poll interval must be between .01 and 5 seconds")
        self.repo, self.store = repository, store
        self.worker_id = worker_id or f"research-{uuid.uuid4()}"
        self.attempt_cost, self.poll_seconds = attempt_cost_usd, poll_seconds
        self.build = LocalReplayEngine().build

    def run_once(self) -> str | None:
        self.repo.worker_seen(self.worker_id, self.build, "idle")
        job = self.repo.claim(self.worker_id)
        if job is None:
            return None
        experiment_id = job.experiment_id
        process = None
        container_name = f"tm-research-{uuid.uuid4().hex}" if job.engine == "lean" else None
        try:
            self.repo.worker_seen(self.worker_id, self.build, "running", experiment_id)
            job, plan, manifest, specs = self.repo.inputs(experiment_id)
            if job.engine == "lean":
                from tradingagents.research.engines.lean import LeanEngine, availability
                status = availability()
                if not status["available"]: raise EngineUnavailable(status["message"] + "; no substitute was run")
                self.build = LeanEngine(container_name=container_name).build
            else:
                self.build = LocalReplayEngine().build
            self.repo.charge(experiment_id, self.worker_id, self.attempt_cost)
            start = last_heartbeat = time.monotonic()
            def tick():
                nonlocal last_heartbeat
                current = self.repo.experiment(experiment_id)
                if current.state != "running" or current.lease_owner != self.worker_id:
                    raise ConflictError("Worker lost authority or the experiment was cancelled")
                now = time.monotonic()
                if now-start > plan.max_runtime_seconds:
                    raise TimeoutError(f"Experiment exceeded its frozen {plan.max_runtime_seconds}s runtime budget")
                if now-last_heartbeat >= 5:
                    self.repo.heartbeat(experiment_id, self.worker_id)
                    self.repo.worker_seen(self.worker_id, self.build, "running", experiment_id)
                    last_heartbeat = now
            from tradingagents.research.evidence.dispatch import dispatch_evidence
            calls = dispatch_evidence(self.repo, self.store, job, plan, manifest, specs, self.worker_id, tick)
            tick()
            costs = {}
            for call in calls:
                from tradingagents.research.contracts import content_hash
                pin = content_hash(call.request["model"])
                costs[pin] = costs.get(pin, Decimal(0)) + Decimal(call.charged_cost_usd)
            request = WorkerInput(engine=job.engine, plan=plan, manifest=manifest, specs=specs, evaluation=job.evaluation,
                inspected_trials=self.repo.family_trial_count(job.family_id), artifact_root=str(self.store.root),
                operating_cost=Decimal(self.repo.experiment(experiment_id).cost_usd), evidence_artifacts=[c.output_artifact for c in calls if c.output_artifact],
                model_call_ids=[c.call_id for c in calls], model_call_costs=costs, container_name=container_name, watch_parent=True)
            with tempfile.TemporaryDirectory(prefix="trademaster-research-") as directory:
                root = Path(directory)
                input_path, output_path, log_path = root / "input.json", root / "result.json", root / "worker.log"
                input_path.write_text(canonical_json(request))
                # Fixed source entry point and validated declarative data only.
                # Do not copy the parent environment's API keys into this process.
                environment = {key: os.environ[key] for key in ("PATH", "TMPDIR", "LANG", "SYSTEMROOT") if key in os.environ}
                environment.update({"PYTHONHASHSEED": "0", "PYTHONUNBUFFERED": "1", "PYTHON_DOTENV_DISABLED": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
                with log_path.open("wb") as log:
                    process = subprocess.Popen([sys.executable, "-m", "tradingagents.research.worker_child", str(input_path), str(output_path)],
                        cwd=Path(__file__).resolve().parents[2], env=environment, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    while process.poll() is None:
                        tick()
                        if log_path.stat().st_size > 5_000_000:
                            raise RuntimeError("Worker output exceeded its bounded log limit")
                        time.sleep(self.poll_seconds)
                if process.returncode != 0 or not output_path.exists():
                    detail = log_path.read_bytes()[-3000:].decode("utf-8", errors="replace")
                    raise RuntimeError(f"Offline engine failed: {detail}")
                if output_path.stat().st_size > 20_000_000:
                    raise RuntimeError("Result summary exceeded its bounded size")
                result = ExperimentResult.model_validate_json(output_path.read_text())
                if result.engine_build != self.build:
                    raise ConflictError("Research source changed during dispatch; result cannot be attributed to the claimed build")
                for digest in result.artifacts.values():
                    self.store.get(digest)
                from tradingagents.research.evaluation.paired_events import verify_paired_artifacts
                verify_paired_artifacts(result.report, result.artifacts, self.store)
                self.repo.finish(experiment_id, self.worker_id, result=result)
        except Exception as exc:
            if process is not None:
                stop_process(process)
            try:
                self.repo.finish(experiment_id, self.worker_id, failure=f"{type(exc).__name__}: {exc}"[:4000])
            except ConflictError:
                # A cancelled/reclaimed job is already authoritative. The old
                # worker cannot overwrite its state or publish a late result.
                pass
        finally:
            if process is not None:
                stop_process(process)
                if process.stdin is not None: process.stdin.close()
            if container_name:
                from tradingagents.research.engines.lean import cleanup_container
                cleanup_container(container_name)
            self.repo.worker_seen(self.worker_id, self.build, "idle")
        return experiment_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--attempt-cost-usd", type=Decimal, default=Decimal(0), help="Conservative operator-configured flat charge per attempt; zero means unmetered local compute")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    engine, sessions = create_session_factory(args.database_url)
    init_db(engine)
    database = engine.url.database
    if not database or database == ":memory:":
        parser.error("a persistent SQLite database is required")
    artifact_root = args.artifacts or os.environ.get("TRADEMASTER_RESEARCH_ARTIFACTS") or Path(database).resolve().parent / ".research-artifacts"
    worker = ResearchWorker(ResearchRepository(sessions), ArtifactStore(artifact_root), attempt_cost_usd=args.attempt_cost_usd)
    try:
        while True:
            result = worker.run_once()
            if args.once:
                break
            if result is None:
                time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        worker.repo.worker_seen(worker.worker_id, worker.build, "stopped")
        engine.dispose()


if __name__ == "__main__":
    main()
