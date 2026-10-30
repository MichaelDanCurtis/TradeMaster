from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from tradingagents.research.contracts import Contract, Digest, Identifier, ModelRevision, Money, PositiveMoney, Text


class Availability(Contract):
    mode: Literal["historical", "observed", "synthetic"]
    event_time: AwareDatetime
    published_at: AwareDatetime
    ingested_at: AwareDatetime
    processed_at: AwareDatetime
    available_at: AwareDatetime
    revision: Identifier
    latency_assumption: Text | None = None

    @model_validator(mode="after")
    def validate_times(self):
        if self.available_at < self.published_at:
            raise ValueError("an observation is never available before publication")
        if self.processed_at < self.ingested_at:
            raise ValueError("processing cannot precede ingestion")
        if self.mode == "observed" and self.available_at < max(self.ingested_at, self.processed_at):
            raise ValueError("observed availability includes receipt and processing")
        if self.mode == "historical" and not self.latency_assumption:
            raise ValueError("historical availability needs an explicit latency assumption")
        return self


class TradingSession(Contract):
    date: date
    opens_at: AwareDatetime
    closes_at: AwareDatetime

    @model_validator(mode="after")
    def check(self):
        if self.closes_at <= self.opens_at:
            raise ValueError("session close must follow open")
        return self


class MarketBar(Contract):
    instrument_id: Identifier
    session: date
    open: PositiveMoney
    high: PositiveMoney
    low: PositiveMoney
    close: PositiveMoney
    volume: Annotated[int, Field(ge=0)]
    available_at: AwareDatetime

    @model_validator(mode="after")
    def check(self):
        if not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("OHLC prices are inconsistent")
        return self


class CorporateAction(Contract):
    action_id: Identifier
    instrument_id: Identifier
    kind: Literal["split", "dividend", "delisting"]
    effective_session: date
    available_at: AwareDatetime
    split_ratio: Annotated[Decimal, Field(gt=0, le=10000)] | None = None
    cash_per_share_usd: Money | None = None
    payable_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def check(self):
        if self.kind == "split" and (self.split_ratio is None or self.cash_per_share_usd is not None):
            raise ValueError("split requires only a ratio")
        if self.kind in {"dividend", "delisting"} and (self.cash_per_share_usd is None or self.split_ratio is not None):
            raise ValueError("cash action requires an explicit amount, including zero")
        if self.kind == "split" and self.payable_at is not None:
            raise ValueError("a split has no cash payment date")
        return self


class SecurityMapping(Contract):
    instrument_id: Identifier
    symbol: Identifier
    valid_from: date
    valid_to: date | None = None
    known_at: AwareDatetime

    @model_validator(mode="after")
    def check(self):
        if self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("security mapping validity is reversed")
        return self


class SourceDocument(Contract):
    model_config = ConfigDict(str_strip_whitespace=False)
    document_id: Identifier
    text: Annotated[str, Field(min_length=1, max_length=12000)]
    text_hash: Digest
    source_url: Text
    availability: Availability

    @model_validator(mode="after")
    def check(self):
        import hashlib
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.text_hash:
            raise ValueError("document text does not match its hash")
        return self


class FinancialObservation(Contract):
    observation_id: Identifier
    instrument_id: Identifier
    metric: Literal["revenue", "operating_cash_flow", "revenue_guidance_low", "revenue_guidance_high"]
    period_start: date
    period_end: date
    period_type: Literal["quarter", "year_to_date", "annual", "forecast"]
    value: Decimal
    original_value: Identifier
    unit: Literal["USD", "USD_thousands", "USD_millions"]
    reporting_basis: Identifier
    document_id: Identifier
    availability: Availability

    @model_validator(mode="after")
    def check(self):
        if not self.value.is_finite() or self.period_end < self.period_start:
            raise ValueError("observation value and period must be valid")
        if self.period_type != "forecast" and self.period_end > self.availability.published_at.date():
            raise ValueError("reported financial period cannot end after publication")
        if self.metric.startswith("revenue_guidance") != (self.period_type == "forecast"):
            raise ValueError("guidance requires a forecast period")
        try:
            if Decimal(self.original_value) != self.value:
                raise ValueError("original value must retain the unscaled provider number")
        except ArithmeticError as exc:
            raise ValueError("original value must be numeric") from exc
        return self

    @property
    def value_usd(self) -> Decimal:
        return self.value * {"USD": Decimal(1), "USD_thousands": Decimal(1000), "USD_millions": Decimal(1000000)}[self.unit]

    @property
    def logical_key(self) -> tuple:
        return (self.instrument_id, self.metric, self.period_start, self.period_end, self.period_type, self.reporting_basis)


class GuidanceNotice(Contract):
    notice_id: Identifier
    instrument_id: Identifier
    document_id: Identifier
    period_start: date
    period_end: date
    reporting_basis: Identifier
    state: Literal["range", "withdrawn"]
    low_observation_id: Identifier | None = None
    high_observation_id: Identifier | None = None
    availability: Availability

    @model_validator(mode="after")
    def check(self):
        if self.period_end < self.period_start:
            raise ValueError("guidance period is reversed")
        if self.state == "range" and (not self.low_observation_id or not self.high_observation_id):
            raise ValueError("a guidance range requires both original numeric observations")
        if self.state == "withdrawn" and (self.low_observation_id or self.high_observation_id):
            raise ValueError("withdrawn guidance cannot retain a numeric range")
        return self


class EvidencePassage(Contract):
    model_config = ConfigDict(str_strip_whitespace=False)
    document_id: Identifier
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]
    quote: Annotated[str, Field(min_length=1, max_length=2000)]


class GuidanceClassification(Contract):
    """Only bounded data; no tool calls, orders, arbitrary code or confidence."""
    schema_version: Literal["guidance_evidence_v1"] = "guidance_evidence_v1"
    notice_id: Identifier
    period_start: date
    period_end: date
    reporting_basis: Identifier
    currency: Literal["USD"]
    guidance_low_usd: Annotated[Decimal, Field(allow_inf_nan=False)] | None
    guidance_high_usd: Annotated[Decimal, Field(allow_inf_nan=False)] | None
    one_time_dependency: Literal["yes", "no", "unknown"]
    reporting_basis_change: Literal["yes", "no", "unknown"]
    unresolved_contradiction: Literal["yes", "no", "unknown"]
    passages: list[EvidencePassage] = Field(max_length=8)

    @property
    def verdict(self) -> str:
        flags = (self.one_time_dependency, self.reporting_basis_change, self.unresolved_contradiction)
        return "exclude" if "yes" in flags else "unknown" if "unknown" in flags else "clean"


class EvidenceObservation(Contract):
    model_config = ConfigDict(str_strip_whitespace=False)
    evidence_id: Identifier
    notice_id: Identifier
    model: ModelRevision
    actual_provider_id: Identifier
    actual_model_id: Identifier
    input_hash: Digest
    input_as_of: AwareDatetime
    raw_output: Annotated[str, Field(max_length=48000)]
    output_hash: Digest
    classification: GuidanceClassification | None
    validation_errors: list[Text] = Field(default_factory=list, max_length=50)
    availability: Availability
    call_started_at: AwareDatetime
    call_completed_at: AwareDatetime
    input_tokens: Annotated[int, Field(ge=0)] | None = None
    output_tokens: Annotated[int, Field(ge=0)] | None = None
    cost_usd: Money
    cost_basis: Literal["provider_reported", "configured_token_rates", "configured_upper_bound", "synthetic_fixture", "subscription_usage"]

    @model_validator(mode="after")
    def check(self):
        import hashlib
        if hashlib.sha256(self.raw_output.encode("utf-8")).hexdigest() != self.output_hash:
            raise ValueError("model output hash does not match the original response")
        if self.call_completed_at < self.call_started_at:
            raise ValueError("model completion precedes dispatch")
        if self.availability.available_at < self.input_as_of:
            raise ValueError("evidence cannot be available before its input cutoff")
        if self.availability.mode == "observed" and self.availability.available_at < self.call_completed_at:
            raise ValueError("prospective evidence cannot be available before model completion")
        if self.cost_basis == "synthetic_fixture" and self.availability.mode != "synthetic":
            raise ValueError("synthetic model calls must retain fixture provenance")
        return self


class HumanEvidenceLabel(Contract):
    notice_id: Identifier
    annotator: Identifier
    labelled_at: AwareDatetime
    expected_verdict: Literal["clean", "exclude", "unknown"]
    rationale: Text


class DatasetBundle(Contract):
    schema_version: Literal[1] = 1
    timezone: Identifier
    sessions: list[TradingSession] = Field(min_length=1, max_length=20000)
    bars: list[MarketBar] = Field(default_factory=list, max_length=2000000)
    actions: list[CorporateAction] = Field(default_factory=list, max_length=100000)
    mappings: list[SecurityMapping] = Field(min_length=1, max_length=20000)
    documents: list[SourceDocument] = Field(default_factory=list, max_length=50000)
    financials: list[FinancialObservation] = Field(default_factory=list, max_length=500000)
    guidance_notices: list[GuidanceNotice] = Field(default_factory=list, max_length=50000)
    evidence: list[EvidenceObservation] = Field(default_factory=list, max_length=50000)
    human_labels: list[HumanEvidenceLabel] = Field(default_factory=list, max_length=50000)

    @model_validator(mode="after")
    def check(self):
        try:
            zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("dataset timezone must be an IANA name") from exc
        calendar = {s.date: s for s in self.sessions}
        if len(calendar) != len(self.sessions) or list(calendar) != sorted(calendar):
            raise ValueError("sessions must be unique and ordered")
        for session in self.sessions:
            if session.opens_at.astimezone(zone).date() != session.date or session.closes_at.astimezone(zone).date() != session.date:
                raise ValueError("session timestamps must match the calendar's local date")
        seen_bars = {}
        for bar in self.bars:
            if bar.session not in calendar or bar.available_at < calendar[bar.session].closes_at:
                raise ValueError("bar unavailable until its known trading session closes")
            key = (bar.instrument_id, bar.session)
            if key in seen_bars and bar != seen_bars[key]:
                raise ValueError("conflicting bars require a new dataset revision")
            seen_bars[key] = bar
        self.bars = sorted(seen_bars.values(), key=lambda b: (b.session, b.instrument_id))
        docs = {d.document_id: d for d in self.documents}
        if len(docs) != len(self.documents):
            raise ValueError("document revisions require distinct IDs")
        obs_ids = set()
        revision_keys = set()
        for observation in self.financials:
            if observation.document_id not in docs:
                raise ValueError("financial observation needs an original source document")
            if observation.availability.available_at < docs[observation.document_id].availability.available_at:
                raise ValueError("extracted fact cannot be available before its document")
            if observation.observation_id in obs_ids:
                raise ValueError("duplicate financial observation ID")
            revision_key = (*observation.logical_key, observation.availability.available_at)
            if revision_key in revision_keys:
                raise ValueError("ambiguous financial revisions at the same availability time")
            obs_ids.add(observation.observation_id)
            revision_keys.add(revision_key)
        known_instruments = {m.instrument_id for m in self.mappings}
        for record in [*self.bars, *self.actions, *self.financials, *self.guidance_notices]:
            if record.instrument_id not in known_instruments:
                raise ValueError("dataset contains an unmapped instrument")
        notices = {n.notice_id: n for n in self.guidance_notices}
        if len(notices) != len(self.guidance_notices):
            raise ValueError("guidance notices must have unique revision IDs")
        facts = {o.observation_id: o for o in self.financials}
        notice_keys = set()
        for notice in self.guidance_notices:
            if notice.document_id not in docs or notice.availability.available_at < docs[notice.document_id].availability.available_at:
                raise ValueError("guidance cannot precede its original source document")
            key = (notice.instrument_id, notice.period_start, notice.period_end, notice.availability.available_at)
            if key in notice_keys:
                raise ValueError("ambiguous guidance revisions at the same availability time")
            notice_keys.add(key)
            for identifier, metric in ((notice.low_observation_id, "revenue_guidance_low"), (notice.high_observation_id, "revenue_guidance_high")):
                if identifier is None:
                    continue
                fact = facts.get(identifier)
                if fact is None or (fact.instrument_id, fact.document_id, fact.period_start, fact.period_end, fact.reporting_basis, fact.metric) != (notice.instrument_id, notice.document_id, notice.period_start, notice.period_end, notice.reporting_basis, metric):
                    raise ValueError("guidance notice and its original numeric observations disagree")
                if fact.availability.available_at > notice.availability.available_at:
                    raise ValueError("guidance notice cannot use a fact before it is available")
        evidence_ids = set()
        for evidence in self.evidence:
            if evidence.evidence_id in evidence_ids or evidence.notice_id not in notices:
                raise ValueError("evidence needs a unique ID and a known guidance notice")
            evidence_ids.add(evidence.evidence_id)
            if evidence.availability.available_at < notices[evidence.notice_id].availability.available_at:
                raise ValueError("extracted evidence cannot precede the guidance notice")
        if len({l.notice_id for l in self.human_labels}) != len(self.human_labels) or any(l.notice_id not in notices for l in self.human_labels):
            raise ValueError("human labels need unique, known notice IDs")
        action_ids = [a.action_id for a in self.actions]
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("corporate actions must have unique IDs")
        for action in self.actions:
            if action.effective_session not in calendar:
                raise ValueError("corporate action effective session is absent")
            if action.payable_at and action.payable_at < calendar[action.effective_session].opens_at:
                raise ValueError("cash payment cannot precede entitlement")
        for index, mapping in enumerate(self.mappings):
            for other in self.mappings[index + 1:]:
                if mapping.instrument_id == other.instrument_id and max(mapping.valid_from, other.valid_from) <= min(mapping.valid_to or date.max, other.valid_to or date.max):
                    raise ValueError("security mapping validity intervals overlap")
        return self

    def as_of(self, timestamp: datetime) -> list[FinancialObservation]:
        if timestamp.tzinfo is None:
            raise ValueError("as-of timestamp must be timezone-aware")
        latest = {}
        for observation in sorted(self.financials, key=lambda o: (o.availability.available_at, o.observation_id)):
            if observation.availability.available_at <= timestamp:
                latest[observation.logical_key] = observation
        return list(latest.values())

    def symbol_at(self, instrument_id: str, timestamp: datetime) -> str | None:
        if timestamp.tzinfo is None:
            raise ValueError("mapping timestamp must be timezone-aware")
        local_date = timestamp.astimezone(ZoneInfo(self.timezone)).date()
        for mapping in self.mappings:
            if mapping.instrument_id == instrument_id and mapping.known_at <= timestamp and mapping.valid_from <= local_date <= (mapping.valid_to or date.max):
                return mapping.symbol
        return None
