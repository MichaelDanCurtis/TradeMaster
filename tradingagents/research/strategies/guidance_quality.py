"""Shared guidance/cash-quality arithmetic. No model, broker or wall-clock I/O."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, Field

from tradingagents.research.contracts import Contract, GuidanceRules, Identifier
from tradingagents.research.data.contracts import DatasetBundle, FinancialObservation, GuidanceNotice

D = Decimal


class GuidanceSignal(Contract):
    notice_id: Identifier
    instrument_id: Identifier
    action: Literal["increase", "cut", "unchanged", "withdrawn", "unknown"]
    reason: str
    available_at: AwareDatetime
    previous_notice_id: str | None = None
    current_midpoint_usd: Decimal | None = None
    previous_midpoint_usd: Decimal | None = None


class CashQuality(Contract):
    status: Literal["pass", "fail", "unknown"]
    reason: str
    period_end: date | None = None
    current_revenue_usd: Decimal | None = None
    current_operating_cash_flow_usd: Decimal | None = None
    prior_revenue_usd: Decimal | None = None
    prior_operating_cash_flow_usd: Decimal | None = None
    current_cash_margin: Decimal | None = None
    prior_cash_margin: Decimal | None = None
    observation_ids: list[str] = Field(default_factory=list)


def notice_range(dataset: DatasetBundle, notice: GuidanceNotice) -> tuple[Decimal, Decimal] | None:
    if notice.state != "range":
        return None
    observations = {o.observation_id: o for o in dataset.financials}
    low, high = observations.get(notice.low_observation_id), observations.get(notice.high_observation_id)
    if low is None or high is None or low.availability.available_at > notice.availability.available_at or high.availability.available_at > notice.availability.available_at:
        return None
    if low.value_usd < 0 or low.value_usd > high.value_usd:
        return None
    return low.value_usd, high.value_usd


def guidance_signal(dataset: DatasetBundle, notice: GuidanceNotice, as_of: datetime) -> GuidanceSignal:
    if as_of.tzinfo is None:
        raise ValueError("guidance decision time must include a timezone")
    result = GuidanceSignal(notice_id=notice.notice_id, instrument_id=notice.instrument_id, action="unknown",
        reason="Guidance is not yet available", available_at=notice.availability.available_at)
    if notice.availability.available_at > as_of:
        return result
    if notice.state == "withdrawn":
        return result.model_copy(update={"action": "withdrawn", "reason": "Explicit withdrawal for the cited forecast period"})
    current = notice_range(dataset, notice)
    if current is None or notice.period_end < as_of.date():
        return result.model_copy(update={"reason": "Invalid, incomplete or expired guidance range"})
    previous = sorted((n for n in dataset.guidance_notices
        if n.instrument_id == notice.instrument_id and n.period_start == notice.period_start and n.period_end == notice.period_end
        and n.availability.available_at < notice.availability.available_at), key=lambda n: (n.availability.available_at, n.notice_id))
    result.current_midpoint_usd = sum(current) / 2
    if not previous:
        result.reason = "No previously public guidance for the same forecast period"
        return result
    prior = previous[-1]
    result.previous_notice_id = prior.notice_id
    prior_range = notice_range(dataset, prior)
    if prior_range is None or prior.reporting_basis != notice.reporting_basis:
        result.reason = "Most recent prior guidance is withdrawn, incomplete or on a different reporting basis"
        return result
    result.previous_midpoint_usd = sum(prior_range) / 2
    difference = result.current_midpoint_usd - result.previous_midpoint_usd
    result.action = "increase" if difference > 0 else "cut" if difference < 0 else "unchanged"
    result.reason = "Compared original numeric revenue-guidance midpoints for identical period, USD currency and reporting basis"
    return result


@dataclass(frozen=True)
class Quarter:
    metric: str
    start: date
    end: date
    value: Decimal
    sources: tuple[str, ...]


def derive_quarters(observations: list[FinancialObservation]) -> tuple[dict[tuple[str, date, date], Quarter], set[tuple[str, date, date]]]:
    """Difference adjacent cumulative reports; never add overlapping YTD totals."""
    candidates: dict[tuple[str, date, date], list[Quarter]] = {}

    def add(metric, start, end, value, sources):
        if 60 <= (end - start).days + 1 <= 110:
            candidates.setdefault((metric, start, end), []).append(Quarter(metric, start, end, value, tuple(sorted(sources))))

    for observation in observations:
        if observation.period_type == "quarter":
            add(observation.metric, observation.period_start, observation.period_end, observation.value_usd, [observation.observation_id])
        elif observation.period_type in {"annual", "year_to_date"}:
            if (observation.period_end - observation.period_start).days + 1 <= 110:
                add(observation.metric, observation.period_start, observation.period_end, observation.value_usd, [observation.observation_id])
            else:
                previous = [o for o in observations if o.metric == observation.metric and o.reporting_basis == observation.reporting_basis
                    and o.period_start == observation.period_start and o.period_end < observation.period_end and o.period_type in {"annual", "year_to_date"}]
                if previous:
                    prior_end = max(o.period_end for o in previous)
                    for prior in (o for o in previous if o.period_end == prior_end):
                        add(observation.metric, prior.period_end + timedelta(days=1), observation.period_end,
                            observation.value_usd - prior.value_usd, [prior.observation_id, observation.observation_id])
    quarters, conflicts = {}, set()
    for key, rows in candidates.items():
        if len({r.value for r in rows}) != 1:
            conflicts.add(key)
        else:
            row = rows[0]
            quarters[key] = Quarter(row.metric, row.start, row.end, row.value, tuple(sorted({source for r in rows for source in r.sources})))
    return quarters, conflicts


def cash_quality(dataset: DatasetBundle, instrument_id: str, as_of: datetime, *, reporting_basis: str = "GAAP", max_age_days: int = 180) -> CashQuality:
    facts = [o for o in dataset.as_of(as_of) if o.instrument_id == instrument_id and o.metric in {"revenue", "operating_cash_flow"}]
    if not facts:
        return CashQuality(status="unknown", reason="No published revenue and operating-cash-flow observations")
    latest_end = max(o.period_end for o in facts)
    if (as_of.date() - latest_end).days > max_age_days:
        return CashQuality(status="unknown", reason="Latest reported financial period exceeds the frozen age limit", period_end=latest_end)
    quarters, conflicts = derive_quarters([o for o in facts if o.reporting_basis == reporting_basis])
    periods, end = [], latest_end
    for _ in range(8):
        starts = {start for metric, start, finish in [*quarters, *conflicts] if finish == end}
        if len(starts) != 1:
            return CashQuality(status="unknown", reason="Need eight unambiguous, consecutive quarters at the latest reported period", period_end=latest_end)
        start = starts.pop()
        keys = [(metric, start, end) for metric in ("revenue", "operating_cash_flow")]
        if any(key in conflicts or key not in quarters for key in keys):
            return CashQuality(status="unknown", reason="Incomplete or contradictory quarter arithmetic on the frozen financial reporting basis", period_end=latest_end)
        periods.append((start, end))
        end = start - timedelta(days=1)
    periods.reverse()
    prior_days = (periods[3][1] - periods[0][0]).days + 1
    current_days = (periods[7][1] - periods[4][0]).days + 1
    if not (330 <= prior_days <= 400 and 330 <= current_days <= 400 and abs(prior_days-current_days) <= 14):
        return CashQuality(status="unknown", reason="Trailing periods are not comparable fiscal years", period_end=latest_end)
    values = {}
    sources = set()
    for label, subset in (("prior", periods[:4]), ("current", periods[4:])):
        for metric in ("revenue", "operating_cash_flow"):
            selected = [quarters[metric, start, end] for start, end in subset]
            values[f"{label}_{metric}_usd"] = sum((q.value for q in selected), D(0))
            sources.update(source for q in selected for source in q.sources)
    result = CashQuality(status="fail", reason="Positive current revenue/cash flow and improved cash margin are required",
        period_end=latest_end, observation_ids=sorted(sources), **values)
    if result.current_revenue_usd <= 0 or result.prior_revenue_usd <= 0:
        return result
    result.current_cash_margin = result.current_operating_cash_flow_usd / result.current_revenue_usd
    result.prior_cash_margin = result.prior_operating_cash_flow_usd / result.prior_revenue_usd
    if result.current_operating_cash_flow_usd > 0 and result.current_cash_margin > result.prior_cash_margin:
        result.status, result.reason = "pass", "Positive current TTM revenue/cash flow; cash flow divided by revenue improved over the comparable prior-year TTM"
    return result


def liquidity_check(dataset: DatasetBundle, instrument_id: str, as_of: datetime, rules: GuidanceRules) -> tuple[bool, str]:
    sessions = [s for s in dataset.sessions if s.closes_at <= as_of][-rules.liquidity_sessions:]
    if len(sessions) < rules.liquidity_sessions:
        return False, "Insufficient completed sessions for the frozen liquidity window"
    dates = {s.date for s in sessions}
    bars = [b for b in dataset.bars if b.instrument_id == instrument_id and b.session in dates and b.available_at <= as_of]
    if len(bars) != len(dates):
        return False, "Missing or late liquidity-window bars"
    if bars[-1].close < rules.min_price_usd:
        return False, "Price is below the frozen liquidity floor"
    average = sum((b.close*b.volume for b in bars), D(0))/len(bars)
    return (True, "Published trailing dollar volume meets the frozen threshold") if average >= rules.min_average_dollar_volume_usd else (False, "Average dollar volume is below the frozen threshold")
