"""Bound the full opt-in observation/cancellation/evaluation worker cycle."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from tradingagents.research.contracts import canonical_json
from tradingagents.research.deployment_health import DeploymentHealth, HEARTBEAT_SECONDS
from tradingagents.research.deployment_jobs import DeploymentJobs
from tradingagents.research.deployment_process import stop_calculation
from tradingagents.research.repository import ConflictError


def cycle_environment(sessions):
    # Only the explicitly configured paper credential may enter the cycle.
    # Keychain resolution happens inside the bounded child, never here.
    environment = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG", "SYSTEMROOT") if key in os.environ}
    from tradingagents.ui.repository import UiRepository
    try:
        config = UiRepository(sessions).get_provider_config("alpaca-paper-broker")
    except KeyError:
        config = None
    if config and config.enabled and config.secret_ref and config.secret_ref.startswith("env:"):
        from tradingagents.ui.secrets import EnvSecretStore
        name = EnvSecretStore._env_name(config.secret_ref)
        if name in os.environ:
            environment[name] = os.environ[name]
    environment.update({"PYTHON_DOTENV_DISABLED": "1", "PYTHONUNBUFFERED": "1", "PYTHONHASHSEED": "0",
        "TRADEMASTER_ENABLE_REAL_RUNS": "0", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
    return environment


class DeploymentSupervisor:
    def __init__(self,sessions,store,*,process_job=True,interval_seconds=15,cycle_timeout_seconds=180):
        self.sessions,self.store=sessions,store
        self.health=DeploymentHealth(sessions)
        self.worker_id="dworker_"+uuid4().hex
        self.process_job=process_job
        self.interval_seconds=interval_seconds
        self.cycle_timeout_seconds=cycle_timeout_seconds
        engine=sessions.kw["bind"]
        database=engine.url.database
        if engine.url.get_backend_name()!="sqlite" or not database or database==":memory:":
            raise ValueError("Deployment supervisor requires persistent SQLite storage")
        self.database_url=f"sqlite:///{Path(database).resolve()}"
        self.process=None
        self.closed=False
        self.health.register(self.worker_id,mode="evaluate" if process_job else "reconcile_only",
            interval_seconds=interval_seconds,cycle_timeout_seconds=cycle_timeout_seconds)

    def run_once(self):
        if self.closed: raise ConflictError("Supervisor has stopped")
        cycle_id="dcycle_"+uuid4().hex
        worker=self.health.start_cycle(self.worker_id,cycle_id)
        result={"status":"cycle_interrupted","message":"Cycle stopped before receiving a completion receipt"}
        try:
            with tempfile.TemporaryDirectory(prefix="trademaster-observer-") as directory:
                root=Path(directory);source=root/"input.json";output=root/"result.json"
                source.write_text(canonical_json({"database_url":self.database_url,"artifact_root":str(self.store.root.resolve()),
                    "worker_id":self.worker_id,"cycle_id":cycle_id,"process_job":self.process_job,
                    "timeout_seconds":self.cycle_timeout_seconds,"build_hash":worker.build_hash}))
                started=last_heartbeat=time.monotonic()
                self.process=subprocess.Popen([sys.executable,"-m","tradingagents.research.deployment_cycle_child",str(source),str(output)],
                    cwd=Path(__file__).resolve().parents[2],env=cycle_environment(self.sessions),stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                while self.process.poll() is None:
                    now=time.monotonic()
                    if now-started>=self.cycle_timeout_seconds:
                        raise TimeoutError("Observation cycle exceeded its fixed runtime")
                    if now-last_heartbeat>=HEARTBEAT_SECONDS:
                        self.health.heartbeat(self.worker_id);last_heartbeat=now
                    if output.exists() and output.stat().st_size>2_000_000:
                        raise ValueError("Cycle response exceeded its bounded size")
                    time.sleep(.1)
                if self.process.returncode or not output.exists() or output.stat().st_size>2_000_000:
                    raise RuntimeError("Observation cycle exited without a valid receipt")
                receipt=json.loads(output.read_text())
                if receipt.get("build_hash")!=worker.build_hash or not isinstance(receipt.get("result"),dict):
                    raise ValueError("Cycle receipt does not match the dispatched build")
                result=receipt["result"]
        except Exception as exc:
            result={"status":"cycle_failed","error_type":type(exc).__name__,
                "message":"Worker cycle failed. Saved observations remain evidence; no order was approved or submitted."}
        finally:
            if self.process is not None:
                stop_calculation(self.process);self.process=None
            # Stop only claims from this confirmed-terminated cycle, plus already
            # expired claims. Preserve terminal receipts and another live worker.
            DeploymentJobs(self.sessions).recover_expired(stopped_cycle_id=cycle_id)
            self.health.finish_cycle(self.worker_id,cycle_id,result)
        return result

    def wait_interval(self):
        until=time.monotonic()+self.interval_seconds
        while time.monotonic()<until:
            time.sleep(min(HEARTBEAT_SECONDS,max(0,until-time.monotonic())))
            self.health.heartbeat(self.worker_id)

    def close(self):
        if not self.closed:
            if self.process is not None:
                stop_calculation(self.process);self.process=None
            self.health.stop(self.worker_id)
            self.closed=True
