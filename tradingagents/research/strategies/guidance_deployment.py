"""Restore prospective guidance state and call the shared event selector."""
from dataclasses import dataclass, field
from datetime import datetime

from tradingagents.research.strategies.guidance_portfolio import GuidancePortfolio, HoldingClock


@dataclass
class GuidanceDeploymentContext:
    start_at: datetime
    holding_clocks: dict[str,dict] = field(default_factory=dict)
    consumed_notices: set[str] = field(default_factory=set)
    pending_entries: set[str] = field(default_factory=set)
    pending_exits: set[str] = field(default_factory=set)
    event_hashes: dict[str,str] = field(default_factory=dict)


def guidance_deployment_selection(dataset,spec,as_of,execution,quantities,context):
    if context is None:
        raise ValueError("Guidance evaluation requires persisted event and actual-fill state")
    if context.start_at.tzinfo is None:
        raise ValueError("Deployment start must have a timezone")
    kernel=GuidancePortfolio(dataset,spec,context.start_at,len(dataset.sessions)-1)
    kernel.consumed=set(context.consumed_notices)
    kernel.last_event_state=dict(context.event_hashes)
    for instrument,quantity in quantities.items():
        if not quantity: continue
        clock=context.holding_clocks.get(instrument)
        if not clock:
            raise ValueError("Attributed guidance holding has no verified opening fill and source notice")
        notice=kernel.notices.get(clock["notice_id"])
        at=clock["entry_at"]
        if at.tzinfo is None or notice is None or notice.instrument_id!=instrument or notice.availability.available_at>at:
            raise ValueError("Holding clock source is missing, mismatched or unavailable at its opening fill")
        index=next((i for i,s in enumerate(dataset.sessions) if s.opens_at<=at<=s.closes_at),None)
        if index is None:
            raise ValueError("Declared calendar does not cover the actual opening fill session")
        kernel.holdings[instrument]=HoldingClock(notice.notice_id,index)
    execution_index=dataset.sessions.index(execution)
    # Future session dates are necessary; future price observations are not.
    # A truncated operational calendar is a data failure, not a research purge
    # that permanently consumes otherwise eligible live notices.
    if execution_index+spec.rules.hold_sessions>=len(dataset.sessions):
        raise ValueError("Prospective calendar does not cover the complete frozen holding horizon")
    retired={a.instrument_id for a in dataset.actions if a.kind=="delisting"
             and a.available_at<=as_of and a.effective_session<=execution.date}
    selected=kernel.select(as_of,execution_index,execution_index,
        {i:int(q) for i,q in quantities.items()},context.pending_entries,context.pending_exits,retired)
    state={"start_at":context.start_at.isoformat(),"consumed_notices":sorted(kernel.consumed),
           "holding_clocks":{i:{"notice_id":c["notice_id"],"entry_at":c["entry_at"].isoformat()} for i,c in context.holding_clocks.items()},
           "pending_entries":sorted(context.pending_entries),"pending_exits":sorted(context.pending_exits),
           "event_hashes":kernel.last_event_state}
    return selected,state
