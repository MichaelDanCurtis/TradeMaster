"""Supervise only this desktop app's loopback services and child process groups."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen

API_PORT = 18897
WEB_PORT = 18898


def emit(state: str, message: str) -> None:
    print(json.dumps({"state": state, "message": message}), flush=True)


def ensure_ports_free(ports):
    # Never attach to, terminate, or trust a pre-existing listener.
    sockets = []
    try:
        for port in ports:
            probe = socket.socket()
            sockets.append(probe)
            probe.bind(("127.0.0.1", port))
    finally:
        for probe in sockets:
            probe.close()


def stop_children(children):
    for child in reversed(children):
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 8
    for child in reversed(children):
        try:
            child.wait(timeout=max(.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
        # Also stop descendants if the direct child exited first.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resources", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    os.umask(0o077)
    resources, data = args.resources.resolve(), args.data_dir.resolve()
    data.mkdir(parents=True, exist_ok=True)
    lock = (data / "desktop.lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        emit("error", "TradeMaster is already running for this data folder.")
        return 1
    children, logs = [], []
    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    database = "sqlite:///" + str(data / "trademaster.db")
    artifacts = data / "artifacts"
    artifacts.mkdir(exist_ok=True)
    log_dir = data / "logs"
    log_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(resources / "backend"), "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHON_DOTENV_DISABLED": "1",
        "TRADINGAGENTS_UI_DATABASE_URL": database,
        "TRADEMASTER_RESEARCH_ARTIFACTS": str(artifacts),
        "TRADINGAGENTS_RESULTS_DIR": str(data / "results"),
        "TRADINGAGENTS_CACHE_DIR": str(data / "cache"),
        "TRADINGAGENTS_MEMORY_LOG_PATH": str(data / "memory" / "trading_memory.md"),
        "TRADEMASTER_API_BASE": f"http://127.0.0.1:{API_PORT}",
        "NEXT_PUBLIC_API_BASE": f"http://127.0.0.1:{API_PORT}",
        "HOSTNAME": "127.0.0.1", "PORT": str(WEB_PORT),
        "NEXT_TELEMETRY_DISABLED": "1", "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
    })
    # GUI launches have a short PATH; preserve normal user-installed Codex locations.
    env["PATH"] = os.pathsep.join([
        str(resources / "node"), str(resources / "python" / "bin"),
        str(Path.home() / ".local" / "bin"), "/opt/homebrew/bin", "/usr/local/bin",
        env.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
    ])
    python = resources / "python" / "bin" / "python3.12"

    def alive():
        if stopping:
            raise InterruptedError()
        if args.parent_pid:
            try:
                os.kill(args.parent_pid, 0)
            except ProcessLookupError:
                raise InterruptedError()
        for child in children:
            if child.poll() is not None:
                raise RuntimeError("A local service stopped unexpectedly. Open Logs for details.")

    def launch(name, command, cwd=data):
        logfile = log_dir / f"{name}.log"
        if logfile.exists() and logfile.stat().st_size > 5_000_000:
            logfile.replace(logfile.with_suffix(".previous.log"))
        log = logfile.open("ab")
        logs.append(log)
        child = subprocess.Popen([str(part) for part in command], cwd=cwd, env=env,
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        children.append(child)
        return child

    def wait_ready(path, key=None, room="market", port=API_PORT):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            alive()
            try:
                request = Request(f"http://127.0.0.1:{port}{path}", headers={"x-trademaster-room": room})
                with urlopen(request, timeout=2) as response:
                    if response.status == 200 and (key is None or json.load(response).get(key)):
                        return
            except (OSError, ValueError):
                pass
            time.sleep(.3)
        raise RuntimeError("A local service did not become ready. Open Logs for details.")

    try:
        ensure_ports_free([API_PORT, WEB_PORT])
        emit("starting", "Starting your local database and API…")
        launch("api", [python, "-m", "uvicorn", "tradingagents.ui.api:create_app", "--factory",
                       "--host", "127.0.0.1", "--port", str(API_PORT)])
        wait_ready("/api/health")
        emit("starting", "Starting research and paper-execution workers…")
        for name, module in [("research", "tradingagents.research.worker"),
                             ("deployments", "tradingagents.research.deployment_worker"),
                             ("scheduler", "tradingagents.scheduling.worker")]:
            launch(name, [python, "-u", "-m", module, "--database-url", database, "--artifacts", artifacts])
        wait_ready("/api/research/runtime", "available", "research")
        wait_ready("/api/research/deployments/runtime", "evaluation_worker_connected")
        wait_ready("/api/execution-schedules/runtime", "connected")
        emit("starting", "Opening the market workstation…")
        launch("web", [resources / "node" / "node", resources / "web" / "apps" / "web" / "server.js"])
        wait_ready("/", port=WEB_PORT)
        emit("ready", f"http://127.0.0.1:{WEB_PORT}/")
        while not stopping:
            alive()
            time.sleep(.5)
    except InterruptedError:
        pass
    except OSError as error:
        emit("error", "TradeMaster could not start. Ports 18897 and 18898 must be free." if error.errno == 48
             else "TradeMaster could not start a bundled service. Open Logs for details.")
        return 1
    except Exception as error:
        emit("error", str(error))
        return 1
    finally:
        stop_children(children)
        for log in logs:
            log.close()
        lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
