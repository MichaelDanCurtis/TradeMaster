"""Bounded worker subprocess entry point; no model or broker credentials needed."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import os
import signal
from threading import Thread

from pydantic import Field

from tradingagents.research.contracts import Contract, Digest, Identifier, Money, ResearchPlanInput, SnapshotManifest, StrategySpec, canonical_json
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.engines.base import EngineUnavailable
from tradingagents.research.engines.replay import LocalReplayEngine
from tradingagents.research.evaluation.comparison import evaluate


class WorkerInput(Contract):
    engine: str
    plan: ResearchPlanInput
    manifest: SnapshotManifest
    specs: dict[str, StrategySpec]
    evaluation: str
    inspected_trials: int = Field(ge=1)
    artifact_root: str
    operating_cost: Money
    evidence_artifacts: list[Digest] = Field(default_factory=list)
    model_call_ids: list[Identifier] = Field(default_factory=list)
    model_call_costs: dict[Digest, Money] = Field(default_factory=dict)
    container_name: str | None = None
    watch_parent: bool = False


def main(input_path: Path, output_path: Path):
    request = WorkerInput.model_validate_json(input_path.read_text())
    if request.watch_parent:
        def parent_exit():
            # Avoid holding Python's buffered-stdin lock while the main thread
            # exits normally; a daemon blocked in BufferedReader aborts CPython.
            os.read(sys.stdin.fileno(), 1)
            os.kill(os.getpid(), signal.SIGTERM)
        # A dead supervisor closes its private pipe. Exit through normal
        # finally blocks so a detached Docker container cannot keep running.
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
        Thread(target=parent_exit, daemon=True).start()
    if request.engine == "local_replay":
        engine = LocalReplayEngine()
    elif request.engine == "lean":
        from tradingagents.research.engines.lean import LeanEngine
        engine = LeanEngine(container_name=request.container_name, timeout_seconds=request.plan.max_runtime_seconds)
    else:
        raise EngineUnavailable(f"Engine {request.engine!r} is unavailable in this worker build; no substitute was run")
    result = evaluate(engine=engine, plan=request.plan, manifest=request.manifest, specs=request.specs,
        evaluation=request.evaluation, inspected_trials=request.inspected_trials, store=ArtifactStore(request.artifact_root), operating_cost=request.operating_cost,
        evidence_artifacts=request.evidence_artifacts, model_call_ids=request.model_call_ids, model_call_costs=request.model_call_costs)
    output_path.write_text(canonical_json(result))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
