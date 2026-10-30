"""Broker-observed regular sessions; never infer holidays from weekdays."""
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import AwareDatetime, Field, StrictBool, model_validator
from tradingagents.research.contracts import Contract, Identifier, content_hash
from tradingagents.research.repository import ConflictError
from tradingagents.ui.models import now_utc

NEW_YORK = ZoneInfo("America/New_York")


class MarketSession(Contract):
    session_date: date
    opens_at: AwareDatetime
    closes_at: AwareDatetime

    @model_validator(mode="after")
    def valid(self):
        if not self.opens_at < self.closes_at:
            raise ValueError("Invalid exchange session bounds")
        if any(t.astimezone(NEW_YORK).date() != self.session_date for t in (self.opens_at, self.closes_at)):
            raise ValueError("Session timestamps disagree with trading date")
        return self


class MarketCalendar(Contract):
    provider_id: Identifier
    account_id: Identifier
    evidence_kind: Literal["broker_paper", "fixture"]
    source: Literal["alpaca-v2-calendar-clock"] = "alpaca-v2-calendar-clock"
    requested_start: date
    requested_end: date
    observed_at: AwareDatetime
    clock_at: AwareDatetime
    is_open: StrictBool
    next_open: AwareDatetime
    next_close: AwareDatetime
    sessions: list[MarketSession] = Field(max_length=32)
    source_hash: str

    @model_validator(mode="after")
    def valid(self):
        if not 0 <= (self.requested_end-self.requested_start).days <= 31:
            raise ValueError("Calendar range must be at most 31 days")
        dates = [s.session_date for s in self.sessions]
        if dates != sorted(set(dates)) or any(not self.requested_start <= d <= self.requested_end for d in dates):
            raise ValueError("Calendar dates are duplicated, unordered, or outside the requested range")
        return self


def alpaca_calendar(broker, start, end):
    if not 0 <= (end-start).days <= 31:
        raise ValueError("Calendar range must be at most 31 days")
    identity = broker.paper_identity()
    rows = broker._read("calendar", {"start":start.isoformat(), "end":end.isoformat(), "date_type":"TRADING"})
    clock = broker._read("clock")
    if not isinstance(rows, list) or len(rows) > 32 or not isinstance(clock, dict):
        raise ValueError("Broker calendar or clock response is invalid")
    from tradingagents.research.data.alpaca_reference import calendar_session
    sessions = []
    for row in rows:
        native = calendar_session(row)
        sessions.append(MarketSession(session_date=native.date, opens_at=native.opens_at, closes_at=native.closes_at))
    return MarketCalendar(provider_id=identity.provider_id,account_id=identity.account_id,
        evidence_kind=broker._evidence_kind,requested_start=start,requested_end=end,observed_at=now_utc(),
        clock_at=clock["timestamp"],is_open=clock["is_open"],next_open=clock["next_open"],next_close=clock["next_close"],
        sessions=sessions,source_hash=content_hash({"calendar":rows,"clock":clock}))


def read_calendar(broker, start, end, snapshot):
    if snapshot.evidence_kind == "fixture": return None
    method = getattr(broker,"execution_calendar",None)
    if not callable(method):
        if snapshot.evidence_kind == "fixture": return None
        raise ConflictError("Broker exchange calendar is unavailable; no scheduled submission is permitted")
    return method(start.astimezone(NEW_YORK).date(),end.astimezone(NEW_YORK).date())


def validate_window(calendar, snapshot, start, end, *, dispatch=False, pinned=None):
    if snapshot.evidence_kind == "fixture" and calendar is None: return None
    if calendar is None: raise ConflictError("Fresh broker calendar evidence is required")
    calendar = MarketCalendar.model_validate(calendar)
    if (calendar.provider_id,calendar.account_id,calendar.evidence_kind) != (snapshot.provider_id,snapshot.account_id,snapshot.evidence_kind):
        raise ConflictError("Calendar belongs to a different account or evidence source")
    now = now_utc()
    if any(not -5 <= (now-t).total_seconds() <= 30 for t in (calendar.observed_at,calendar.clock_at)):
        raise ConflictError("Broker calendar or clock is stale; refresh before proceeding")
    session = next((s for s in calendar.sessions if s.opens_at <= start < end <= s.closes_at-timedelta(seconds=60)),None)
    if session is None:
        raise ConflictError("Schedule must fit one verified regular market session, ending at least 60 seconds before close; holidays and closed hours are excluded")
    if pinned is not None and pinned != session.model_dump(mode="json"):
        raise ConflictError("Exchange session changed since review; prepare a new schedule")
    if dispatch and (not calendar.is_open or not session.opens_at <= now < session.closes_at-timedelta(seconds=60)):
        raise ConflictError("Broker reports the market closed or outside the reviewed session; new submission blocked")
    return session.model_dump(mode="json")


def check_dispatch(sessions, order, broker, snapshot):
    from sqlmodel import select
    from tradingagents.scheduling.models import ScheduledLeg, ExecutionSchedule, ScheduleEvent
    with sessions() as session:
        leg = session.exec(select(ScheduledLeg).where(ScheduledLeg.order_id==order.order_id)).first()
        if leg is None or snapshot.evidence_kind == "fixture": return
        schedule = session.get(ExecutionSchedule,leg.schedule_id)
        if not schedule.payload.get("market_session"):
            raise ConflictError("Legacy schedule has no verified exchange session; prepare a new schedule")
        start=datetime.fromisoformat(schedule.payload["request"]["start_at"])
        end=datetime.fromisoformat(schedule.payload["ends_at"])
        calendar=read_calendar(broker,start,end,snapshot)
        validate_window(calendar,snapshot,start,end,dispatch=True,pinned=schedule.payload["market_session"])
        session.add(ScheduleEvent(schedule_id=schedule.schedule_id,kind="market_session_checked",
            payload={"order_id":order.order_id,"calendar":calendar.model_dump(mode="json")}))
        session.commit()
