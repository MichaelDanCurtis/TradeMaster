"""Persistent paper scheduler; only explicitly approved exact children can dispatch."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from threading import Thread
import time
from uuid import uuid4
from tradingagents.scheduling.repository import ScheduleRepository
from tradingagents.research.deployment_process import stop_calculation
from tradingagents.research.deployment_supervisor import cycle_environment
from tradingagents.ui.db import create_session_factory, init_db


def child(database_url):
    if os.getpgrp() != os.getpid(): raise RuntimeError("Scheduler cycle needs a private process group")
    def parent_exit():
        os.read(sys.stdin.fileno(), 1)
        os.killpg(os.getpgrp(), signal.SIGKILL)
    Thread(target=parent_exit, daemon=True).start()
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, 120)
    from tradingagents.research.deployment_cycle_child import resolve_configured_broker
    from tradingagents.research.accounting_repository import PaperAccountingRepository
    from tradingagents.research.accounting_service import ReconciledPaperBroker
    from tradingagents.scheduling.service import tick
    engine, sessions = create_session_factory(database_url)
    try:
        result = tick(sessions, lambda: ReconciledPaperBroker(resolve_configured_broker(sessions), PaperAccountingRepository(sessions)))
        print(json.dumps(result), flush=True)
    finally: engine.dispose()


def cycle(repo, database_url, worker_id, timeout=120):
    process = None
    repo.heartbeat(worker_id, "running")
    try:
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen([sys.executable,"-m","tradingagents.scheduling.worker","--database-url",database_url,"--child"],
                cwd=Path(__file__).resolve().parents[2], env=cycle_environment(repo.sessions), stdin=subprocess.PIPE,
                stdout=output, stderr=subprocess.DEVNULL, start_new_session=True)
            started = heartbeat = time.monotonic()
            while process.poll() is None:
                if time.monotonic()-started > timeout: raise TimeoutError("Scheduler cycle exceeded deadline")
                if output.tell() > 100000: raise ValueError("Scheduler receipt exceeds limit")
                if time.monotonic()-heartbeat >= 5:
                    repo.heartbeat(worker_id, "running"); heartbeat = time.monotonic()
                time.sleep(.1)
            if process.returncode: raise RuntimeError("Scheduler child exited without a completion receipt")
            output.seek(0)
            result = json.loads(output.read(100000))
            if not isinstance(result, dict) or "status" not in result: raise ValueError("Invalid scheduler receipt")
    except Exception as exc:
        # A killed submission may have reached the broker. Fence further work;
        # the durable exact-order claim remains the recovery authority.
        for row in repo.active():
            repo.pause_on_error(row.schedule_id, "Scheduler cycle interrupted; reconcile existing orders before resuming")
        result = {"status":"cycle_failed", "error_type":type(exc).__name__}
    finally:
        if process is not None: stop_calculation(process)
    repo.heartbeat(worker_id, "idle", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--artifacts", help=argparse.SUPPRESS)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.child: return child(args.database_url)
    from dotenv import load_dotenv
    load_dotenv()
    engine, sessions = create_session_factory(args.database_url)
    if engine.url.get_backend_name() != "sqlite" or not engine.url.database or engine.url.database == ":memory:":
        parser.error("Scheduler requires persistent SQLite storage")
    init_db(engine)
    repo = ScheduleRepository(sessions); worker_id = "scheduler_"+uuid4().hex
    try:
        while True:
            print(json.dumps(cycle(repo, args.database_url, worker_id)), flush=True)
            if args.once: break
            time.sleep(2)
    except KeyboardInterrupt: pass
    finally:
        repo.heartbeat(worker_id, "stopped"); engine.dispose()


if __name__ == "__main__": main()
