"""Shared event selection and actual-fill holding clocks; no execution or I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, Field

from tradingagents.research.contracts import Contract, GuidanceRules, StrategySpec, content_hash
from tradingagents.research.data.contracts import DatasetBundle
from tradingagents.research.evidence.validation import evidence_verdict
from tradingagents.research.strategies.guidance_quality import CashQuality, cash_quality, guidance_signal, liquidity_check
from tradingagents.research.strategies.trend import TargetDecision, cap_weights
from decimal import Decimal


class GuidanceEventDecision(Contract):
    notice_id: str
    instrument_id: str
    at: AwareDatetime
    action: str
    status: Literal["eligible", "abstain", "excluded", "already_held", "pending", "consumed", "purged", "expired", "exit"]
    reason: str
    quality: CashQuality | None = None
    evidence_id: str | None = None
    evidence_verdict: str | None = None


@dataclass(frozen=True)
class HoldingClock:
    notice_id: str
    entry_session_index: int


@dataclass
class GuidanceSelection:
    target: TargetDecision
    entries: dict[str, str] = field(default_factory=dict)
    exits: dict[str, str] = field(default_factory=dict)
    cancel_entries: set[str] = field(default_factory=set)
    events: list[GuidanceEventDecision] = field(default_factory=list)


class GuidancePortfolio:
    """One entry attempt per notice; repeated notices never reset an open lot.

    Weights are allocated across the frozen universe before filtering. Excluded
    issuers leave cash rather than increasing the surviving issuers' weights.
    """
    def __init__(self, dataset: DatasetBundle, spec: StrategySpec, start_at: datetime, last_session_index: int):
        if not isinstance(spec.rules, GuidanceRules):
            raise ValueError("guidance portfolio requires guidance rules")
        self.dataset, self.spec, self.start_at, self.last_index = dataset, spec, start_at, last_session_index
        self.notices = {n.notice_id: n for n in dataset.guidance_notices}
        self.holdings: dict[str, HoldingClock] = {}
        self.consumed: set[str] = set()
        self.last_event_state: dict[str, str] = {}
        self.weights = cap_weights({i.instrument_id: Decimal(1) for i in spec.universe}, spec)

    def filled(self, instrument: str, quantity_change: int, resulting_quantity: int, index: int, notice_id: str | None):
        if quantity_change > 0 and instrument not in self.holdings:
            if notice_id is None:
                raise ValueError("guidance fill has no source event")
            self.holdings[instrument] = HoldingClock(notice_id, index)
        if resulting_quantity == 0:
            self.holdings.pop(instrument, None)

    def select(self, as_of: datetime, base_execution_index: int, execution_index: int,
               quantities: dict[str, int], pending_entries: set[str], pending_exits: set[str], retired: set[str]) -> GuidanceSelection:
        rules = self.spec.rules
        result = GuidanceSelection(TargetDecision(status="no_signal", reason="No eligible new guidance event or due exit"))
        visible = sorted((n for n in self.dataset.guidance_notices if n.instrument_id in quantities
            and n.availability.available_at+timedelta(seconds=rules.decision_latency_seconds) <= as_of),
            key=lambda n: (n.availability.available_at, n.notice_id))
        latest = {}
        for n in visible:
            latest[n.instrument_id, n.period_start, n.period_end] = n

        def emit(n, signal, status, reason, **extra):
            row = GuidanceEventDecision(notice_id=n.notice_id, instrument_id=n.instrument_id, at=as_of,
                action=signal.action, status=status, reason=reason, **extra)
            digest = content_hash(row.model_dump(mode="json", exclude={"at"}))
            if self.last_event_state.get(n.notice_id) != digest:
                self.last_event_state[n.notice_id] = digest
                result.events.append(row)

        # Exits are governed by the first actual fill. A repeat release, delayed
        # fill or rejected order cannot manufacture a new holding start date.
        for instrument, holding in list(self.holdings.items()):
            if not quantities[instrument]:
                self.holdings.pop(instrument)
                continue
            entry = self.notices[holding.notice_id]
            current = latest.get((instrument, entry.period_start, entry.period_end), entry)
            signal = guidance_signal(self.dataset, current, as_of)
            reason = None
            if signal.action in {"cut", "withdrawn"}:
                reason = f"{signal.action}: {current.notice_id}"
            elif base_execution_index >= holding.entry_session_index + rules.hold_sessions:
                reason = f"Frozen {rules.hold_sessions}-session hold from the first actual fill"
            if reason and instrument not in pending_exits:
                result.exits[instrument] = reason
                emit(current, signal, "exit", reason)

        for n in visible:
            if n.availability.available_at < self.start_at:
                continue  # prior disclosures are comparison inputs, not fresh entries
            signal = guidance_signal(self.dataset, n, as_of)
            instrument = n.instrument_id
            if latest[instrument, n.period_start, n.period_end].notice_id != n.notice_id:
                continue
            if signal.action in {"withdrawn", "cut"}:
                result.cancel_entries.add(instrument)
                continue
            if signal.action != "increase":
                # A pending entry is a proposal, not an existing investment.
                # Loss of a comparable, supported increase invalidates it.
                if instrument in pending_entries:
                    result.cancel_entries.add(instrument)
                emit(n, signal, "abstain", signal.reason)
                continue
            if n.notice_id in self.consumed:
                continue
            if quantities[instrument] or instrument in pending_entries:
                # No pyramiding and no later re-entry from a release seen while
                # holding an earlier event. The pending/held event owns its clock.
                self.consumed.add(n.notice_id)
                emit(n, signal, "already_held" if quantities[instrument] else "pending", "Repeat event does not add shares or reset the holding clock")
                continue
            first_window = next((i for i, s in enumerate(self.dataset.sessions)
                if s.opens_at > n.availability.available_at+timedelta(seconds=rules.decision_latency_seconds)), len(self.dataset.sessions))
            if base_execution_index >= first_window + rules.entry_validity_sessions:
                self.consumed.add(n.notice_id)
                emit(n, signal, "expired", "No entry before the frozen event-validity window ended")
                continue
            delay = execution_index - base_execution_index
            if execution_index + rules.hold_sessions + delay > self.last_index:
                self.consumed.add(n.notice_id)
                emit(n, signal, "purged", "Entry and complete delayed holding horizon would cross the evaluation boundary")
                continue
            if instrument in retired:
                self.consumed.add(n.notice_id)
                emit(n, signal, "excluded", "Instrument retired before entry")
                continue
            liquid, reason = liquidity_check(self.dataset, instrument, as_of, rules)
            if not liquid:
                emit(n, signal, "abstain", reason)
                continue
            quality = None
            if rules.arm != "guidance_control":
                quality = cash_quality(self.dataset, instrument, as_of, reporting_basis=rules.financial_reporting_basis,
                    max_age_days=rules.max_financial_age_days)
                if quality.status != "pass":
                    emit(n, signal, "excluded" if quality.status == "fail" else "abstain", quality.reason, quality=quality)
                    continue
            evidence_id, verdict = None, None
            if rules.arm == "astra_challenger":
                # The earliest completed attempt for this exact input is used.
                # Later retries cannot replace an unfavorable answer. A genuinely
                # newer source packet may be classified when it becomes available.
                records = sorted((e for e in self.dataset.evidence if e.notice_id == n.notice_id and e.model == self.spec.model
                    and e.availability.available_at <= as_of), key=lambda e: (e.input_as_of, e.call_started_at, e.evidence_id))
                from tradingagents.research.evidence.extraction import extraction_input, input_hash
                packet = extraction_input(self.dataset, n, as_of)
                matching = [e for e in records if e.input_hash == input_hash(packet)]
                record = matching[0] if matching else None
                verdict, errors = evidence_verdict(record, self.dataset, n, self.spec.model, as_of) if record else ("unknown", ["No completed classification for the currently available source packet"])
                evidence_id = record.evidence_id if record else None
                if verdict != "clean":
                    emit(n, signal, "excluded" if verdict == "exclude" else "abstain", "; ".join(errors) if errors else "Classifier found excluded or unresolved evidence",
                        quality=quality, evidence_id=evidence_id, evidence_verdict=verdict)
                    continue
            result.entries[instrument] = n.notice_id
            emit(n, signal, "eligible", "All frozen entry rules passed", quality=quality, evidence_id=evidence_id, evidence_verdict=verdict)
        weights = {i: self.weights[i] for i in result.entries}
        weights.update({i: Decimal(0) for i in result.exits})
        if weights:
            result.target = TargetDecision(status="targets", reason="Guidance events and exits; retained positions keep their existing quantities", weights=weights)
        return result

    def submitted(self, entries: dict[str, str]):
        self.consumed.update(entries.values())
