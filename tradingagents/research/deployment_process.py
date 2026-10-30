"""Killable prospective calculation using saved inputs and no broker credentials."""
from datetime import datetime, timezone
from contextlib import closing
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

from tradingagents.research.contracts import canonical_json
from tradingagents.research.repository import ConflictError, require


class DeploymentCalculationError(RuntimeError):
    pass


def stop_calculation(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
    if process.stdin is not None:
        process.stdin.close()


def _live_claim(connection, job_id, owner):
    # A separate read connection has a short busy timeout. It cannot wait on a
    # slow writer for the application connection's full timeout.
    row = connection.execute(
        "SELECT state, owner, lease_until, deadline FROM research_deployment_jobs WHERE job_id=?",
        (job_id,),
    ).fetchone()
    now = datetime.now(timezone.utc)
    if row is None or row[0] != "running" or row[1] != owner or not row[2] or not row[3]:
        raise ConflictError("Evaluation canceled or ownership changed; calculation stopped")
    limits = [datetime.fromisoformat(value) for value in row[2:]]
    limits = [value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value for value in limits]
    if now >= min(limits):
        raise ConflictError("Evaluation lease expired; calculation stopped")
    return (limits[1] - now).total_seconds()


def evaluate_in_process(sessions, identifier, request, reconciliation_id, store, *, job_fence):
    from tradingagents.research.deployment_evaluation import _BUILD
    from tradingagents.research.deployment_models import DeploymentEvaluationRecord
    from tradingagents.research.deployment_jobs import live_job

    engine = sessions.kw["bind"]
    database = engine.url.database
    if engine.url.get_backend_name() != "sqlite" or not database or database == ":memory:":
        raise DeploymentCalculationError("Isolated deployment evaluation requires a persistent SQLite database")
    database = str(Path(database).resolve())
    with sessions() as session:
        job = live_job(session, *job_fence)
        if job.deployment_id != identifier or job.request != request.model_dump(mode="json"):
            raise ConflictError("Calculation inputs differ from the claimed job")

    with closing(sqlite3.connect(f"file:{quote(database, safe='/')}?mode=ro", uri=True, timeout=.1)) as monitor:
        remaining = _live_claim(monitor, *job_fence)
        deadline = time.monotonic() + remaining
        with tempfile.TemporaryDirectory(prefix="trademaster-deployment-") as directory:
            root = Path(directory)
            source, output = root / "input.json", root / "result.json"
            source.write_text(canonical_json({
                "database_url": f"sqlite:///{database}", "job_id": job_fence[0], "owner": job_fence[1],
                "reconciliation_id": reconciliation_id, "artifact_root": str(store.root.resolve()),
                "build_hash": _BUILD, "runtime_seconds": remaining,
            }))
            environment = {key: os.environ[key] for key in ("PATH", "TMPDIR", "LANG", "SYSTEMROOT") if key in os.environ}
            environment.update({"HOME": str(root), "PYTHONHASHSEED": "0", "PYTHONUNBUFFERED": "1",
                "PYTHON_DOTENV_DISABLED": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
            process = subprocess.Popen(
                [sys.executable, "-m", "tradingagents.research.deployment_child", str(source), str(output)],
                cwd=Path(__file__).resolve().parents[2], env=environment, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise ConflictError("Evaluation runtime expired; calculation stopped")
                    _live_claim(monitor, *job_fence)
                    if output.exists() and output.stat().st_size > 20_000:
                        raise DeploymentCalculationError("Calculation response exceeded its size bound")
                    time.sleep(.1)
                _live_claim(monitor, *job_fence)
                if process.returncode or not output.exists() or output.stat().st_size > 20_000:
                    raise DeploymentCalculationError("Calculation process exited without a valid receipt")
                result = json.loads(output.read_text())
                if result.get("status") == "conflict":
                    raise ConflictError(result["message"])
                if result.get("status") != "completed" or result.get("build_hash") != _BUILD:
                    raise DeploymentCalculationError("Calculation failed or its loaded build changed")
                with sessions() as session:
                    live_job(session, *job_fence)
                    evaluation = require(session, DeploymentEvaluationRecord, result["evaluation_id"])
                    if evaluation.deployment_id != identifier or evaluation.terms_id != job.terms_id:
                        raise ConflictError("Calculation receipt belongs to another deployment or funding revision")
                    return evaluation
            finally:
                stop_calculation(process)
