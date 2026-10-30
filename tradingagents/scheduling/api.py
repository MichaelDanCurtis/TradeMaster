from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Header, HTTPException
from tradingagents.scheduling.calendar import NEW_YORK, read_calendar
from tradingagents.ui.models import now_utc
import requests
from tradingagents.research.repository import ConflictError, MissingRecordError
from tradingagents.scheduling.contracts import ScheduleRequest, ScheduleAction
from tradingagents.scheduling.repository import ScheduleRepository
from tradingagents.ui.room_policy import enforce_room_tool


def create_scheduler_router(sessions, broker_service):
    router = APIRouter(prefix="/api/execution-schedules", tags=["execution-schedules"])
    repo = ScheduleRepository(sessions)
    def grant(x_trademaster_room: str = Header(default="research")):
        try: enforce_room_tool(x_trademaster_room, "broker-paper-preview")
        except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
    def call(operation, *args):
        try: return operation(*args)
        except MissingRecordError as exc: raise HTTPException(404, str(exc)) from exc
        except ConflictError as exc: raise HTTPException(409, str(exc)) from exc
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
        except PermissionError as exc: raise HTTPException(403, str(exc)) from exc
        except requests.RequestException as exc: raise HTTPException(503, "Paper broker observation unavailable") from exc
    @router.get("/runtime", dependencies=[Depends(grant)])
    def runtime(): return repo.runtime()
    @router.get("/calendar", dependencies=[Depends(grant)])
    def calendar():
        def operation():
            broker = broker_service()._broker
            snapshot = broker.paper_snapshot()
            now = now_utc()
            result = read_calendar(broker, now, now+timedelta(days=14), snapshot)
            if result is None: raise ConflictError("Fixture broker has no verified exchange calendar")
            return result
        return call(operation)

    @router.get("", dependencies=[Depends(grant)])
    def listing(): return {"schedules":repo.listing()}
    @router.post("", dependencies=[Depends(grant)])
    def prepare(request: ScheduleRequest):
        def operation():
            service = broker_service()
            snapshot = service._broker.paper_snapshot()
            calendar = read_calendar(service._broker, request.start_at, request.start_at+timedelta(minutes=request.duration_minutes), snapshot)
            row = repo.prepare(request, snapshot, service._execution_policy(), calendar)
            return repo.detail(row.schedule_id)
        return call(operation)
    @router.get("/{identifier}", dependencies=[Depends(grant)])
    def detail(identifier: str): return call(repo.detail, identifier)
    @router.post("/{identifier}/actions", dependencies=[Depends(grant)])
    def action(identifier: str, request: ScheduleAction):
        def operation():
            snapshot = calendar = None
            if request.action in {"approve", "resume"}:
                broker = broker_service()._broker
                snapshot = broker.paper_snapshot()
                row = repo.detail(identifier)["schedule"]
                calendar = read_calendar(broker, datetime.fromisoformat(row.payload["request"]["start_at"]),
                    datetime.fromisoformat(row.payload["ends_at"]), snapshot)
            repo.action(identifier, request, snapshot, calendar)
            return repo.detail(identifier)
        return call(operation)
    return router
