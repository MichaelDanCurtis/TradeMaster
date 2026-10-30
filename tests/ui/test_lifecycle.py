import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradingagents.ui.lifecycle import application_lifespan, on_lifecycle


def test_lifespan_starts_workers_and_closes_dependents_first():
    app = FastAPI(lifespan=application_lifespan)
    events = []

    @on_lifecycle(app, 'startup')
    def open_resource():
        events.append('open')

    @on_lifecycle(app, 'startup')
    async def start_worker():
        events.append('start')

    @on_lifecycle(app, 'shutdown')
    def close_resource():
        events.append('close')

    @on_lifecycle(app, 'shutdown')
    async def stop_worker():
        events.append('stop')

    with TestClient(app):
        assert events == ['open', 'start']
    assert events == ['open', 'start', 'stop', 'close']


def test_failed_startup_still_cleans_resources_despite_cleanup_failure():
    app = FastAPI(lifespan=application_lifespan)
    events = []

    @on_lifecycle(app, 'startup')
    def fail_start():
        raise RuntimeError('startup failure')

    @on_lifecycle(app, 'shutdown')
    def close_resource():
        events.append('closed')

    @on_lifecycle(app, 'shutdown')
    def fail_cleanup():
        raise ValueError('cleanup failure')

    with pytest.raises(ExceptionGroup, match='shutdown failed') as exc:
        with TestClient(app):
            pass
    assert events == ['closed']
    assert isinstance(exc.value.exceptions[0], ValueError)
    assert isinstance(exc.value.__context__, RuntimeError)
