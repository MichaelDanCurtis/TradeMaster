"""Saved-input calculation child. No broker adapter, provider keys or submissions."""
import json
import os
from pathlib import Path
import signal
import sys
from threading import Thread


def watch_parent():
    # A private pipe closes when the supervisor dies, including SIGKILL. Avoid
    # buffered stdin and terminate the entire isolated process group directly.
    os.read(sys.stdin.fileno(), 1)
    os.killpg(os.getpgrp(), signal.SIGKILL)


def main(source, output):
    if os.getpgrp() != os.getpid():
        raise RuntimeError("Calculation child requires its own process group")
    Thread(target=watch_parent, daemon=True).start()
    envelope = json.loads(source.read_text())
    # Kernel wall-clock timer also bounds blocked imports/calculation if the
    # parent is alive but cannot run its monitor. A deadline cannot be extended.
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, max(.001, min(120, envelope["runtime_seconds"])))
    from tradingagents.research.contracts import canonical_json
    from tradingagents.research.data.store import ArtifactStore
    from tradingagents.research.deployment_contracts import DeploymentEvaluationInput
    from tradingagents.research.deployment_evaluation import DeploymentEvaluator, _BUILD
    from tradingagents.research.deployment_jobs import live_job
    from tradingagents.research.repository import ConflictError
    from tradingagents.ui.db import create_session_factory
    engine, sessions = create_session_factory(envelope["database_url"])
    try:
        if _BUILD != envelope["build_hash"]:
            raise ConflictError("Calculation build changed since dispatch; request a fresh evaluation")
        fence = (envelope["job_id"], envelope["owner"])
        with sessions() as session:
            job = live_job(session, *fence)
        result = DeploymentEvaluator(sessions).evaluate(job.deployment_id,
            DeploymentEvaluationInput.model_validate(job.request), envelope["reconciliation_id"],
            ArtifactStore(envelope["artifact_root"]), job_fence=fence)
        receipt = {"status": "completed", "evaluation_id": result.evaluation_id, "build_hash": _BUILD}
    except ConflictError as exc:
        receipt = {"status": "conflict", "message": str(exc)[:1000]}
    except Exception as exc:
        receipt = {"status": "failed", "error_type": type(exc).__name__}
    finally:
        engine.dispose()
    output.write_text(canonical_json(receipt))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
