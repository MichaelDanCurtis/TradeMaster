"""One bounded provider observation cycle, started only by an explicit worker."""
import json
import os
from pathlib import Path
import signal
import sys
from threading import Thread


def resolve_configured_broker(sessions):
    from tradingagents.ui.api import _resolve_broker_adapter
    from tradingagents.ui.repository import UiRepository
    from tradingagents.ui.brokers.alpaca import AlpacaPaperBroker
    broker=_resolve_broker_adapter(UiRepository(sessions),{})
    if not isinstance(broker,AlpacaPaperBroker):
        raise PermissionError("No configured paper provider; the observer does not substitute a fixture account")
    return broker


def main(source,output):
    if os.getpgrp()!=os.getpid():
        raise RuntimeError("Cycle child requires an isolated process group")
    def parent_exit():
        os.read(sys.stdin.fileno(),1)
        os.killpg(os.getpgrp(),signal.SIGKILL)
    Thread(target=parent_exit,daemon=True).start()
    envelope=json.loads(source.read_text())
    signal.signal(signal.SIGALRM,signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL,max(.001,min(600,envelope["timeout_seconds"])))
    from tradingagents.ui.db import create_session_factory
    from tradingagents.research.data.store import ArtifactStore
    from tradingagents.research.deployment_health import DeploymentHealth,worker_build
    from tradingagents.research.deployment_worker import maintenance_cycle
    from tradingagents.research.contracts import canonical_json
    if worker_build()!=envelope["build_hash"]:
        raise RuntimeError("Worker source changed since supervisor startup; restart the worker")
    engine,sessions=create_session_factory(envelope["database_url"])
    health=DeploymentHealth(sessions)
    try:
        result=maintenance_cycle(sessions,lambda:resolve_configured_broker(sessions),ArtifactStore(envelope["artifact_root"]),
            process_job=envelope["process_job"],cycle_id=envelope["cycle_id"],
            progress=lambda phase,**fields:health.progress(envelope["worker_id"],envelope["cycle_id"],phase,**fields))
        output.write_text(canonical_json({"result":result,"build_hash":envelope["build_hash"]}))
    finally:
        engine.dispose()


if __name__=="__main__":
    main(Path(sys.argv[1]),Path(sys.argv[2]))
