"""Drive due orders through the existing at-most-once paper dispatch boundary."""
from sqlmodel import select
from tradingagents.research.execution_contracts import TERMINAL
from tradingagents.research.execution_repository import PaperExecutionRepository
from tradingagents.research.execution_service import PaperExecutionService
from tradingagents.scheduling.models import ExecutionSchedule
from tradingagents.scheduling.repository import ScheduleRepository, FINAL
from tradingagents.ui.models import now_utc


def tick(sessions, broker_resolver):
    repo = ScheduleRepository(sessions)
    with sessions() as session:
        rows = list(session.exec(select(ExecutionSchedule).where(ExecutionSchedule.state.in_(["active","paused","stopping"])).order_by(ExecutionSchedule.created_at)))
    if not rows:
        return {"status":"idle", "schedules":0}
    try:
        service = PaperExecutionService(PaperExecutionRepository(sessions), broker_resolver())
    except Exception as exc:
        for row in rows: repo.pause_on_error(row.schedule_id, f"Broker unavailable ({type(exc).__name__}); no new submission")
        return {"status":"provider_unavailable"}
    for row in rows:
        for leg in repo.detail(row.schedule_id)["legs"]:
            # Re-read before each dispatch; the final transaction also fences
            # pause/stop/deadline against simultaneous UI and worker actions.
            current = repo.detail(row.schedule_id)["schedule"]
            if current.state in FINAL: break
            order = leg["order"]
            attempt = service.repo.attempt_for_order(order.order_id)
            try:
                if attempt and attempt.state not in TERMINAL:
                    attempt = service.reconcile(order)
                if order.state in TERMINAL or (attempt and attempt.state in TERMINAL): continue
                if current.state == "stopping" or now_utc() >= leg["expires_at"]:
                    service.cancel(order, "scheduler-stop" if current.state == "stopping" else "scheduler-deadline")
                elif attempt and attempt.state in {"unknown","dispatching"}:
                    repo.pause_on_error(row.schedule_id, "Submission outcome is uncertain; reconcile the existing client order ID before resuming")
                elif not attempt and current.state == "active" and leg["due_at"] <= now_utc():
                    outcome = service.submit(order)
                    if outcome.state in {"unknown","dispatching","rejected"}:
                        repo.pause_on_error(row.schedule_id, "Broker submission needs review; automatic retries are disabled")
            except Exception as exc:
                repo.pause_on_error(row.schedule_id, f"Order blocked ({type(exc).__name__}): " + (str(exc)[:300] if isinstance(exc, ValueError) else "broker observation unavailable"))
        repo.finish_if_terminal(row.schedule_id)
    return {"status":"observed", "schedules":len(rows)}
