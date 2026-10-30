"""Durable metered extraction within a claimed experiment, before offline replay."""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

from tradingagents.research.contracts import canonical_json, content_hash
from tradingagents.research.data.contracts import EvidenceObservation
from tradingagents.research.evaluation.comparison import evaluation_window
from tradingagents.research.evidence.extraction import extraction_input, input_hash
from tradingagents.research.evidence.provider import pinned_binding, validate_input_bound, validate_billing
from tradingagents.research.strategies.guidance_quality import guidance_signal
from tradingagents.ui.repository import UiRepository


def dispatch_evidence(repo, store, job, plan, manifest, specs, worker_id, tick):
    if plan.extraction is None:
        return []
    if manifest.evidence_kind == "fixture":
        raise ValueError("New provider calls cannot be billed against a synthetic fixture plan; use preserved fixture outputs")
    if manifest.evidence_kind == "prospective" and plan.extraction.availability_mode != "observed":
        raise ValueError("Prospective source snapshots require actual model-arrival timing")
    dataset = store.dataset(manifest)
    start, end = evaluation_window(plan, dataset, job.evaluation)
    zone = ZoneInfo(dataset.timezone)
    models = {}
    for version_id, spec in specs.items():
        if spec.model:
            models.setdefault(content_hash(spec.model), (version_id, spec))
    candidates = []
    for version_id, spec in models.values():
        instruments = {i.instrument_id for i in spec.universe}
        for notice in dataset.guidance_notices:
            if notice.instrument_id not in instruments or not start <= notice.availability.available_at.astimezone(zone).date() <= end:
                continue
            if guidance_signal(dataset, notice, notice.availability.available_at).action != "increase":
                continue
            cutoff = notice.availability.available_at if plan.extraction.availability_mode == "historical" else max(job.started_at, notice.availability.available_at)
            packet = extraction_input(dataset, notice, cutoff)
            digest = input_hash(packet)
            if any(e.model == spec.model and e.input_hash == digest and e.notice_id == notice.notice_id for e in dataset.evidence):
                continue  # imported failures and unfavorable answers are not replaced
            validate_input_bound(canonical_json(packet), plan.extraction)
            candidates.append((notice.availability.available_at, notice.notice_id, version_id, spec, cutoff, digest))
    if len(candidates) > plan.extraction.max_calls:
        raise ValueError("Source snapshot requires more model calls than the frozen limit; no partial selection was dispatched")
    registry = UiRepository(repo.sessions)
    existing = {(c.notice_id, content_hash(c.request["model"]), c.input_hash, c.input_as_of): c for c in repo.model_calls(job.experiment_id)}
    for _, notice_id, version_id, spec, cutoff, digest in sorted(candidates, key=lambda item: (item[0], item[1], item[2])):
        tick()
        previous = existing.get((notice_id, content_hash(spec.model), digest, cutoff))
        if previous:
            if previous.state in {"reserved", "dispatched"}:
                repo.abandon_model_call(previous.call_id, worker_id, "Recovered interrupted call; provider outcome unconfirmed")
            continue
        binding = pinned_binding(registry, spec.model)
        validate_billing(binding, plan.extraction)
        # Resolve only the selected credential, before charging. Never place it
        # in the database, artifact, command line or the offline replay process.
        credential = binding.credential()
        if not isinstance(credential, str) or len(credential.encode()) > 8192:
            raise ValueError("Configured credential exceeds the bounded dispatch envelope")
        row, fresh = repo.reserve_model_call(job.experiment_id, worker_id, version_id=version_id, notice_id=notice_id,
            input_hash=digest, input_as_of=cutoff, provider_fingerprint=binding.config_hash)
        if not fresh:
            if row.state in {"reserved", "dispatched"}:
                repo.abandon_model_call(row.call_id, worker_id, "Recovered interrupted call; provider outcome unconfirmed")
            continue  # at most one dispatch of the same economic model request
        process = None
        try:
            row = repo.dispatch_model_call(row.call_id, worker_id)
            payload = {"manifest": manifest.model_dump(mode="json"), "artifact_root": str(store.root), "notice_id": notice_id,
                "input_as_of": cutoff.isoformat(), "model": spec.model.model_dump(mode="json"), "policy": plan.extraction.model_dump(mode="json"),
                "binding": asdict(binding), "credential": credential}
            envelope = canonical_json(payload).encode()
            if len(envelope) > 20000:
                raise ValueError("Model dispatch envelope is too large")
            environment = {k: os.environ[k] for k in ("PATH", "TMPDIR", "LANG", "SYSTEMROOT") if k in os.environ}
            environment.update(PYTHONHASHSEED="0", PYTHONUNBUFFERED="1", PYTHON_DOTENV_DISABLED="1")
            with tempfile.TemporaryDirectory(prefix="trademaster-extraction-") as directory:
                output, log = Path(directory)/"receipt.json", Path(directory)/"extractor.log"
                with log.open("wb") as stream:
                    process = subprocess.Popen([sys.executable, "-m", "tradingagents.research.evidence.child", str(output)],
                        cwd=Path(__file__).resolve().parents[3], env=environment, stdin=subprocess.PIPE,
                        stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                    process.stdin.write(envelope)
                    process.stdin.close()
                    del envelope, payload, credential
                    launched = time.monotonic()
                    while process.poll() is None:
                        tick()
                        if time.monotonic()-launched > plan.extraction.timeout_seconds+5:
                            raise TimeoutError("Model process exceeded its frozen timeout")
                        if log.stat().st_size > 1000000:
                            raise ValueError("Model process exceeded its bounded output")
                        time.sleep(.05)
                if process.returncode != 0 or not output.exists() or output.stat().st_size > 150000:
                    raise RuntimeError("Model process returned no bounded receipt; provider outcome unconfirmed")
                evidence = EvidenceObservation.model_validate_json(output.read_text())
                artifact = store.put_json(evidence)
                repo.complete_model_call(row.call_id, worker_id, evidence, artifact)
                if any("exceeded" in e for e in evidence.validation_errors):
                    raise ValueError("Provider exceeded a frozen bound; further model dispatch stopped")
        except Exception:
            repo.abandon_model_call(row.call_id, worker_id, "Interrupted bounded extraction; provider outcome unconfirmed")
            raise
        finally:
            if process is not None:
                from tradingagents.research.worker import stop_process
                stop_process(process)
    return repo.model_calls(job.experiment_id)
