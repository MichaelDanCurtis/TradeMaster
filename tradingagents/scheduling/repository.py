"""Immutable schedule terms, atomic approvals, and the final dispatch fence."""
from datetime import datetime, timedelta
from decimal import Decimal as D, ROUND_DOWN, ROUND_UP
from sqlalchemy import text
from sqlmodel import select
from tradingagents.algorithms import preview
from tradingagents.research.contracts import content_hash
from tradingagents.research.execution_contracts import ExactPaperOrder, ExecutionPolicy, TERMINAL
from tradingagents.research.execution_models import ExactPaperOrderRecord
from tradingagents.research.execution_repository import PaperExecutionRepository, account_key, risk_check
from tradingagents.research.repository import ResearchRepository, ConflictError, require
from tradingagents.scheduling.models import ExecutionSchedule, ScheduledLeg, ScheduleEvent, SchedulerWorker
from tradingagents.ui.models import now_utc

CAPABILITIES = {"twap": "Timed, fixed-limit whole-share slices", "dca_ladder": "Resting whole-share limit orders at reviewed price rungs"}
FINAL = {"completed", "stopped", "expired", "finished_partial"}


def require_schedule_approval(session, order_id, allowed):
    if not allowed and session.exec(select(ScheduledLeg).where(ScheduledLeg.order_id == order_id)).first():
        raise ConflictError("Approve this order through its complete schedule review")


def check_scheduled_dispatch(session, order):
    leg = session.exec(select(ScheduledLeg).where(ScheduledLeg.order_id == order.order_id)).first()
    if leg is None:
        return
    schedule = require(session, ExecutionSchedule, leg.schedule_id)
    if schedule.state != "active" or schedule.approved_at is None:
        raise ConflictError("Schedule is not active; new submissions are blocked")
    if not leg.due_at <= now_utc() < leg.expires_at:
        raise ConflictError("Scheduled slice is not due or its submission window expired")
    if schedule.content_hash != content_hash(schedule.payload):
        raise ConflictError("Schedule terms differ from the reviewed content")
    pinned = next((p for p in schedule.payload["legs"] if p["order_id"] == order.order_id), None)
    if not pinned or pinned["order_hash"] != order.content_hash:
        raise ConflictError("Scheduled child differs from its reviewed exact order")


class ScheduleRepository(ResearchRepository):
    def prepare(self, request, snapshot, policy, calendar=None):
        request_hash = content_hash(request)
        with self.transaction() as session:
            existing = session.exec(select(ExecutionSchedule).where(ExecutionSchedule.idempotency_key == request.idempotency_key)).first()
            if existing:
                if existing.request_hash != request_hash:
                    raise ConflictError("This preparation key already identifies different schedule terms")
                return existing
            now = now_utc()
            if not now+timedelta(seconds=10) <= request.start_at <= now+timedelta(days=7):
                raise ConflictError("Schedule must start between 10 seconds and 7 days from now")
            params = {"slices": request.count, "window_minutes": request.duration_minutes} if request.algorithm == "twap" else {"rungs": request.count, "span_percent": float(request.span_percent)}
            plan = preview(algorithm=request.algorithm, symbol=request.symbol, side=request.side,
                notional=float(request.notional_usd), reference_price=float(request.limit_price_usd), parameters=params)
            end = request.start_at+timedelta(minutes=request.duration_minutes)
            from tradingagents.scheduling.calendar import validate_window
            market_session = validate_window(calendar, snapshot, request.start_at, end)
            exacts = []
            total_cents = int(request.notional_usd*100)
            for index, source in enumerate(plan.legs):
                limit = D(str(source.price)).quantize(D(".01"), rounding=ROUND_DOWN if request.side == "buy" else ROUND_UP)
                budget = D(total_cents//request.count + (total_cents%request.count if index == request.count-1 else 0))/100
                quantity = int(budget/limit) if limit > 0 else 0
                if quantity < 1:
                    raise ConflictError("Every slice must fund at least one whole share; increase budget or reduce slice count")
                due = request.start_at if request.algorithm == "dca_ladder" else request.start_at+timedelta(seconds=index*request.duration_minutes*60//request.count)
                deadline = end if request.algorithm == "dca_ladder" else request.start_at+timedelta(seconds=(index+1)*request.duration_minutes*60//request.count)
                exacts.append((due, ExactPaperOrder(symbol=request.symbol, side=request.side, quantity=quantity,
                    limit_price_usd=limit, expires_at=deadline, time_in_force="gtc")))
            aggregate = exacts[0][1].model_copy(update={"quantity":sum(o.quantity for _,o in exacts),
                "limit_price_usd":max(o.limit_price_usd for _,o in exacts)})
            pending, attempts = PaperExecutionRepository._pending(session, account_key(snapshot))
            risk_check(snapshot, aggregate, policy, pending, attempts)
            from tradingagents.research.deployment_repository import check_deployment_order
            check_deployment_order(session, None, None, snapshot, aggregate, policy)
            schedule = ExecutionSchedule(idempotency_key=request.idempotency_key, request_hash=request_hash,
                account_key=account_key(snapshot), content_hash="pending", payload={}, review_expires_at=min(now+timedelta(minutes=5),request.start_at))
            session.add(schedule); session.flush()
            execution = PaperExecutionRepository(self.sessions)
            pins = []
            for index, (due, exact) in enumerate(exacts):
                order = execution.preview(None, exact, policy, snapshot, budget=exact.maximum_notional_usd,
                    intent_payload={"execution_schedule_id":schedule.schedule_id}, session=session)
                leg = ScheduledLeg(schedule_id=schedule.schedule_id, order_id=order.order_id, ordinal=index+1,
                    due_at=due, expires_at=exact.expires_at)
                session.add(leg)
                pins.append({"order_id":order.order_id,"order_hash":order.content_hash,"due_at":due.isoformat(),
                    "order":exact.model_dump(mode="json")})
            maximum = sum(o.maximum_notional_usd for _,o in exacts)
            schedule.payload = {"version":"paper-scheduler-v1", "request":request.model_dump(mode="json"),
                "account_id":snapshot.account_id,"provider_id":snapshot.provider_id,"evidence_kind":snapshot.evidence_kind,
                "policy":policy.model_dump(mode="json"),"legs":pins,
                "market_session":market_session,"calendar_evidence":calendar.model_dump(mode="json") if calendar else None,"maximum_notional_usd":str(maximum),
                "unused_budget_usd":str(request.notional_usd-maximum),"ends_at":end.isoformat(),
                "notes":["Fixed limits; no market fallback or automatic repricing", "Missed time windows are skipped, never caught up", "Verified regular session; holidays and closed hours excluded, deadlines at least 60 seconds before close" if market_session else "Fixture schedule; no broker exchange calendar verified",
                    "Pause stops new submissions; existing broker orders remain working until canceled or their schedule deadline",
                    "Stop requests cancellation; unconfirmed broker outcomes retain reservations",
                    "Approval covers every listed exact order; current account risk is checked again per submission"]}
            schedule.content_hash = content_hash(schedule.payload)
            session.add(schedule)
            session.add(ScheduleEvent(schedule_id=schedule.schedule_id, kind="prepared", payload={"content_hash":schedule.content_hash}))
        return schedule

    def action(self, identifier, request, snapshot=None, calendar=None):
        with self.transaction() as session:
            row = require(session, ExecutionSchedule, identifier)
            if row.content_hash != request.expected_hash or row.revision != request.expected_revision:
                raise ConflictError("Schedule changed; refresh and review its current state")
            legs = list(session.exec(select(ScheduledLeg).where(ScheduledLeg.schedule_id == identifier)))
            execution = PaperExecutionRepository(self.sessions)
            orders = [require(session, ExactPaperOrderRecord, leg.order_id) for leg in legs]
            if request.action in {"approve", "resume"} and row.payload["evidence_kind"] != "fixture":
                from tradingagents.scheduling.calendar import validate_window
                if snapshot is None or account_key(snapshot) != row.account_key: raise ConflictError("Fresh facts for the reviewed account are required")
                if snapshot.evidence_kind != "fixture" and not row.payload.get("market_session"):
                    raise ConflictError("Legacy schedule has no verified exchange session; prepare a new schedule")
                validate_window(calendar, snapshot, datetime.fromisoformat(row.payload["request"]["start_at"]),
                    datetime.fromisoformat(row.payload["ends_at"]), pinned=row.payload.get("market_session"))
            if request.action == "approve":
                if row.state != "previewed" or now_utc() >= row.review_expires_at:
                    raise ConflictError("Schedule review expired or is no longer approvable; prepare a new schedule")
                if snapshot is None or account_key(snapshot) != row.account_key:
                    raise ConflictError("Fresh facts for the reviewed account are required")
                live = list(session.exec(select(ExecutionSchedule).where(ExecutionSchedule.state.in_(["active","paused","stopping"]))))
                if len(live) >= 8:
                    raise ConflictError("At most eight schedules may be active or awaiting cancellation")
                exacts = [ExactPaperOrder.model_validate(order.order) for order in orders]
                aggregate = exacts[0].model_copy(update={"quantity":sum(o.quantity for o in exacts),"limit_price_usd":max(o.limit_price_usd for o in exacts)})
                pending, attempts = execution._pending(session, row.account_key)
                risk_check(snapshot, aggregate, ExecutionPolicy.model_validate(row.payload["policy"]), pending, attempts)
                from tradingagents.research.deployment_repository import check_deployment_order
                check_deployment_order(session, None, None, snapshot, aggregate, ExecutionPolicy.model_validate(row.payload["policy"]))
                for order in orders:
                    execution.approve(order.order_id, request.actor, order.content_hash, session=session, schedule_approval=True)
                row.state, row.approved_at = "active", now_utc()
            elif request.action == "pause":
                if row.state != "active": raise ConflictError("Only an active schedule can be paused")
                row.state = "paused"
            elif request.action == "resume":
                if row.state != "paused": raise ConflictError("Only a paused schedule can be resumed")
                if all(leg.expires_at <= now_utc() for leg in legs): raise ConflictError("All schedule windows expired; prepare a new schedule")
                row.state = "active"
            else:
                if row.state in FINAL: raise ConflictError("Schedule is already terminal")
                row.state = "stopping"
                for order in orders:
                    execution.request_cancel(order.order_id, request.actor, session=session)
                if all(order.state in TERMINAL for order in orders):
                    row.state = "stopped"
            row.revision += 1
            row.message = {"approve":"Exact schedule approved; awaiting due windows", "pause":"New submissions paused; existing broker orders can still fill",
                "resume":"Resumed within original deadlines; missed windows are skipped", "stop":"New submissions blocked; waiting for cancellation reconciliation"}[request.action]
            if row.state == "stopped": row.message = "Stopped locally; no outstanding broker orders"
            session.add(row)
            session.add(ScheduleEvent(schedule_id=identifier, kind=request.action, payload={"actor":request.actor,"content_hash":row.content_hash,"revision":row.revision,
                "calendar":calendar.model_dump(mode="json") if calendar else None}))
        return row

    def pause_on_error(self, identifier, message):
        with self.transaction() as session:
            row = require(session, ExecutionSchedule, identifier)
            if row.state == "active":
                row.state = "paused"; row.revision += 1; row.message = message[:500]
                session.add(row)
                session.add(ScheduleEvent(schedule_id=identifier, kind="risk_or_provider_pause", payload={"message":row.message}))

    def detail(self, identifier):
        with self.sessions() as session:
            row = require(session, ExecutionSchedule, identifier)
            legs = list(session.exec(select(ScheduledLeg).where(ScheduledLeg.schedule_id == identifier).order_by(ScheduledLeg.ordinal)))
            execution = PaperExecutionRepository(self.sessions)
            result = []
            for leg in legs:
                order = require(session, ExactPaperOrderRecord, leg.order_id)
                attempt = execution.attempt_for_order(order.order_id)
                result.append({**leg.model_dump(),"order":order,"attempt":attempt})
            events = list(session.exec(select(ScheduleEvent).where(ScheduleEvent.schedule_id == identifier).order_by(ScheduleEvent.created_at)))
            return {"schedule":display_schedule(row),"legs":result,"events":events}

    def active(self):
        with self.sessions() as session:
            return list(session.exec(select(ExecutionSchedule).where(ExecutionSchedule.state.in_(["active","paused","stopping"]))))

    def listing(self):
        with self.sessions() as session:
            recent = list(session.exec(select(ExecutionSchedule).order_by(ExecutionSchedule.created_at.desc()).limit(100)))
        return [display_schedule(row) for row in {row.schedule_id:row for row in [*self.active(), *recent]}.values()]

    def finish_if_terminal(self, identifier):
        with self.transaction() as session:
            row = require(session, ExecutionSchedule, identifier)
            if row.state in FINAL or row.state == "previewed": return
            legs = list(session.exec(select(ScheduledLeg).where(ScheduledLeg.schedule_id == identifier)))
            states = [require(session, ExactPaperOrderRecord, leg.order_id).state for leg in legs]
            if all(state in TERMINAL for state in states):
                row.state = "stopped" if row.state == "stopping" else "completed" if all(state == "filled" for state in states) else "finished_partial"
                row.revision += 1; row.message = "All child orders are closed; inspect broker receipts and local cancellations separately"
                session.add(row); session.add(ScheduleEvent(schedule_id=identifier, kind=row.state))

    def heartbeat(self, worker_id, state="idle", result=None):
        with self.transaction() as session:
            row = session.get(SchedulerWorker, worker_id) or SchedulerWorker(worker_id=worker_id)
            row.state, row.last_seen_at = state, now_utc()
            if result is not None: row.result = result
            session.add(row)

    def runtime(self):
        with self.sessions() as session:
            workers = list(session.exec(select(SchedulerWorker).where(SchedulerWorker.last_seen_at > now_utc()-timedelta(seconds=20))))
            connected = any(w.state != "stopped" for w in workers)
            return {"connected":connected,"workers":workers,"capabilities":CAPABILITIES,
                "message":"Scheduler heartbeat received" if connected else "Scheduler offline; no due orders will be sent"}


def install_schedule_guards(engine):
    with engine.begin() as connection:
        for table in ("execution_schedule_legs", "execution_schedule_events"):
            for action in ("UPDATE", "DELETE"):
                connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'schedule evidence is immutable'); END"))
        # A newly inserted schedule is assembled within one transaction, then
        # permanently pinned as soon as its first content hash is assigned.
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS execution_schedule_pin BEFORE UPDATE ON execution_schedules WHEN OLD.content_hash != 'pending' AND (OLD.payload IS NOT NEW.payload OR OLD.content_hash IS NOT NEW.content_hash OR OLD.account_key IS NOT NEW.account_key OR OLD.request_hash IS NOT NEW.request_hash OR OLD.idempotency_key IS NOT NEW.idempotency_key OR OLD.review_expires_at IS NOT NEW.review_expires_at) BEGIN SELECT RAISE(ABORT, 'schedule terms are immutable'); END"))
        connection.execute(text("CREATE TRIGGER IF NOT EXISTS execution_schedule_no_delete BEFORE DELETE ON execution_schedules BEGIN SELECT RAISE(ABORT, 'schedule history is immutable'); END"))


def display_schedule(row):
    """Correct legacy display copy without rewriting historical stored evidence."""
    if row.message == "All child orders have terminal receipts; inspect observed fills":
        return row.model_copy(update={"message": "All child orders are closed; inspect broker receipts and local cancellations separately"})
    return row
