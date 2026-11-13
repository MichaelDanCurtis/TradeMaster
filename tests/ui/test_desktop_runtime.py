"""Desktop lifecycle checks: occupied ports are never adopted or terminated."""
import importlib.util
from pathlib import Path
import socket
import subprocess
import sys

import pytest

path = Path(__file__).resolve().parents[2] / 'desktop/runtime.py'
spec = importlib.util.spec_from_file_location('desktop_runtime', path)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def test_existing_listener_is_rejected_and_remains_usable():
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        server.listen()
        port = server.getsockname()[1]
        with pytest.raises(OSError):
            runtime.ensure_ports_free([port])
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            accepted, _ = server.accept()
            accepted.close()


def test_shutdown_only_reaps_owned_process_groups():
    owned = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    try:
        runtime.stop_children([owned])
        assert owned.poll() is not None
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_desktop_cors_allows_only_the_explicit_local_origin(tmp_path):
    from fastapi.testclient import TestClient
    from tradingagents.ui.api import create_app
    with TestClient(create_app(database_url='sqlite:///' + str(tmp_path / 'desktop.db'))) as client:
        good = client.get('/api/health', headers={'Origin': 'http://127.0.0.1:18898'})
        assert good.headers['access-control-allow-origin'] == 'http://127.0.0.1:18898'
        bad = client.get('/api/health', headers={'Origin': 'https://untrusted.example'})
        assert 'access-control-allow-origin' not in bad.headers
