"""Offline LEAN execution adapter. Never pulls images or substitutes an engine."""
from __future__ import annotations

from datetime import timedelta, timezone
import hashlib
from functools import lru_cache
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from tradingagents.research.contracts import canonical_json, content_hash
from tradingagents.research.engines.base import EngineUnavailable, ReplayRequest, ReplayResult, source_build

IMAGE = "quantconnect/lean@sha256:8ba05f8a5425efb3b2d32299803a5d3bd5da953caf4597804b6763c8d9fa8736"


def docker_path() -> str:
    value = shutil.which("docker")
    if not value:
        raise EngineUnavailable("Docker is unavailable; install the pinned LEAN image explicitly before selecting LEAN")
    return value


def availability() -> dict:
    try:
        result = subprocess.run([docker_path(), "image", "inspect", IMAGE, "--format", "{{.Id}}"], capture_output=True, text=True, timeout=5)
        if result.returncode or result.stdout.strip() != IMAGE.split("@")[1]:
            raise EngineUnavailable("Pinned LEAN image is not available in the running Docker engine")
        return {"available": True, "image": IMAGE, "message": "Pinned offline LEAN image available"}
    except (EngineUnavailable, OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "image": IMAGE, "message": str(exc)[:500]}


@lru_cache(maxsize=1)
def cached_availability(time_bucket: int) -> dict:
    return availability()


def configuration() -> dict:
    return {
        "environment": "backtesting", "live-mode": False,
        "algorithm-type-name": "TradeMasterResearch", "algorithm-language": "Python",
        "algorithm-location": "/Code/tradingagents/research/engines/lean_algorithm.py", "data-folder": "/Lean/Data",
        "results-destination-folder": "/Results", "object-store-root": "/Results/storage",
        "log-handler": "QuantConnect.Logging.CompositeLogHandler", "messaging-handler": "QuantConnect.Messaging.Messaging",
        "job-queue-handler": "QuantConnect.Queues.JobQueue", "api-handler": "QuantConnect.Api.Api",
        "map-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskMapFileProvider",
        "factor-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskFactorFileProvider",
        "data-provider": "QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider", "data-channel-provider": "DataChannelProvider",
        "object-store": "QuantConnect.Lean.Engine.Storage.LocalObjectStore", "data-aggregator": "QuantConnect.Lean.Engine.DataFeeds.AggregationManager",
        "job-user-id": "0", "job-project-id": "0", "job-organization-id": "", "maximum-data-points-per-chart-series": 10000,
        "environments": {"backtesting": {"live-mode": False,
            "setup-handler": "QuantConnect.Lean.Engine.Setup.BacktestingSetupHandler",
            "result-handler": "QuantConnect.Lean.Engine.Results.BacktestingResultHandler",
            "data-feed-handler": "QuantConnect.Lean.Engine.DataFeeds.FileSystemDataFeed",
            "real-time-handler": "QuantConnect.Lean.Engine.RealTime.BacktestingRealTimeHandler",
            "history-provider": ["QuantConnect.Lean.Engine.HistoricalData.SubscriptionDataReaderHistoryProvider"],
            "transaction-handler": "QuantConnect.Lean.Engine.TransactionHandlers.BacktestingTransactionHandler"}},
    }


def clock_times(request: ReplayRequest):
    sessions = [s for s in request.dataset.sessions if request.start <= s.date <= request.end]
    if not sessions:
        raise EngineUnavailable("Evaluation has no declared sessions")
    delay = timedelta(seconds=request.spec.rules.decision_latency_seconds)
    times = {at for s in sessions for at in (s.opens_at, s.closes_at, s.closes_at + delay)}
    times.update(row.availability.available_at + delay for row in [*request.dataset.guidance_notices, *request.dataset.financials, *request.dataset.evidence]
        if sessions[0].opens_at <= row.availability.available_at + delay and (row.availability.available_at + delay).date() <= request.end)
    return sorted(times)


def export_inputs(request: ReplayRequest, root: Path, build: str, source_manifest: dict | None = None):
    root.mkdir(parents=True, exist_ok=True)
    symbols = {i.instrument_id: f"I{index:04d}" for index, i in enumerate(sorted(request.spec.universe, key=lambda i: i.instrument_id))}
    (root/"request.json").write_text(canonical_json({"request": request.model_dump(mode="json"), "build": build, "symbols": symbols, "input_hash": content_hash(request), "source_manifest": source_manifest or {}}))
    (root/"config.json").write_text(canonical_json(configuration()))
    times = clock_times(request)
    def stamp(at): return at.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="microseconds")
    (root/"CLOCK.csv").write_text("".join(f"{stamp(at)},1\n" for at in times))
    for instrument, symbol in symbols.items():
        updates = {}
        for bar in request.dataset.bars:
            if bar.instrument_id != instrument: continue
            session = next(s for s in request.dataset.sessions if s.date == bar.session)
            updates[session.opens_at], updates[session.closes_at] = bar.open, bar.close
        ordered = sorted(updates.items())
        position, price, rows = 0, None, []
        for at in times:
            while position < len(ordered) and ordered[position][0] <= at:
                price = ordered[position][1]
                position += 1
            if price is not None: rows.append(f"{stamp(at)},{price}\n")
        (root/f"{symbol}.csv").write_text("".join(rows))


def cleanup_container(name: str) -> None:
    try:
        subprocess.run([docker_path(), "rm", "--force", name], capture_output=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired, EngineUnavailable):
        pass


class LeanEngine:
    def __init__(self, *, container_name: str | None = None, timeout_seconds: int = 120, output_directory: Path | None = None):
        self.container_name = container_name or f"tm-research-{uuid.uuid4().hex}"
        if not self.container_name.startswith("tm-research-") or not self.container_name.replace("-", "").isalnum():
            raise ValueError("Invalid research container name")
        self.timeout, self.output_directory = timeout_seconds, output_directory

    @property
    def build(self) -> str:
        return "lean-v1-" + content_hash({"source": source_build("research"), "image": IMAGE})

    def run(self, request: ReplayRequest) -> ReplayResult:
        status = availability()
        if not status["available"]: raise EngineUnavailable(status["message"])
        with tempfile.TemporaryDirectory(prefix="trademaster-lean-") as directory:
            root = Path(directory)
            inputs, outputs, code = root/"inputs", root/"outputs", root/"code"
            outputs.mkdir()
            package = code/"tradingagents"
            package.mkdir(parents=True)
            (package/"__init__.py").write_text("")
            # Copy only research source, never the workspace's settings or keys.
            source = Path(__file__).resolve().parents[1]
            manifest = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.rglob("*.py"))}
            build = self.build
            shutil.copytree(source, package/"research", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            if any(hashlib.sha256((package/"research"/p).read_bytes()).hexdigest() != digest for p, digest in manifest.items()) or self.build != build:
                raise EngineUnavailable("Research source changed while preparing LEAN")
            export_inputs(request, inputs, build, manifest)
            process = None
            try:
                with (outputs/"launcher.log").open("wb") as log:
                    process = subprocess.Popen([docker_path(), "run", "--rm", "--pull", "never", "--name", self.container_name,
                        "--network", "none", "--cpus", "2", "--memory", "3g", "--pids-limit", "256", "--cap-drop", "ALL",
                        "--security-opt", "no-new-privileges", "-e", "PYTHONHASHSEED=0", "-e", "PYTHON_DOTENV_DISABLED=1", "-e", "PYTHONPATH=/Code",
                        "-v", f"{inputs}:/Inputs:ro", "-v", f"{code}:/Code:ro", "-v", f"{outputs}:/Results",
                        IMAGE, "--config", "/Inputs/config.json"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                    start = time.monotonic()
                    while process.poll() is None:
                        if time.monotonic()-start > self.timeout: raise TimeoutError("LEAN container exceeded its runtime bound")
                        if sum(p.stat().st_size for p in outputs.rglob("*") if p.is_file()) > 50_000_000: raise EngineUnavailable("LEAN output exceeded its size bound")
                        time.sleep(.1)
                path = outputs/"result.json"
                if process.returncode or not path.exists():
                    detail = (outputs/"launcher.log").read_text(errors="replace")[-4000:]
                    raise EngineUnavailable(f"LEAN did not produce a completed research artifact: {detail}")
                result = ReplayResult.model_validate_json(path.read_text())
                if result.engine_build != build: raise EngineUnavailable("LEAN result build does not match the dispatched source")
                return result
            finally:
                cleanup_container(self.container_name)
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
                if self.output_directory:
                    shutil.copytree(outputs, self.output_directory, dirs_exist_ok=True)
