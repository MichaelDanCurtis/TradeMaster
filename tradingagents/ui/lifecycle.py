"""Compose local worker callbacks through the ASGI lifespan protocol."""
from contextlib import asynccontextmanager
from inspect import isawaitable


def on_lifecycle(app, event):
    if event not in ("startup", "shutdown"):
        raise ValueError("Unsupported lifecycle event")
    if not hasattr(app.state, "lifecycle_handlers"):
        app.state.lifecycle_handlers = {"startup": [], "shutdown": []}

    def register(callback):
        app.state.lifecycle_handlers[event].append(callback)
        return callback

    return register


async def _invoke(callback):
    result = callback()
    if isawaitable(result):
        await result


@asynccontextmanager
async def application_lifespan(app):
    handlers = getattr(app.state, "lifecycle_handlers", {"startup": [], "shutdown": []})
    try:
        for callback in handlers["startup"]:
            await _invoke(callback)
        yield
    finally:
        # Stop dependent workers before closing their underlying resources.
        # Run every cleanup even if another fails.
        errors = []
        for callback in reversed(handlers["shutdown"]):
            try:
                await _invoke(callback)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup("Application shutdown failed", errors)
