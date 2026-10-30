"""Shared event-driven portfolio policy and independent accounting ledger.

Signals see only observations available at the declared decision time. Quantities
are fixed then; opening gaps never retrospectively improve those quantities.
At the later execution window, orders that breach current risk/cash limits are
unfilled. This is a conservative daily simulation, not an auction-fill promise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN

from tradingagents.research.contracts import GuidanceRules, TrendRules
from tradingagents.research.engines.base import (
    AccountingEvent, DecisionRecord, EngineUnavailable, EquityPoint, Fill,
    ReplayRequest, ReplayResult,
)
from tradingagents.research.strategies.trend import TargetDecision, cap_weights, trend_targets
from tradingagents.research.strategies.guidance_portfolio import GuidancePortfolio
from tradingagents.research.strategies.guidance_quality import liquidity_check

D = Decimal
ZERO = D(0)


def whole(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_DOWN))


@dataclass
class Account:
    cash: Decimal
    quantities: dict[str, int]
    basis: dict[str, Decimal]
    marks: dict[str, Decimal] = field(default_factory=dict)
    receivables: list[tuple[str, Decimal, datetime | None, str]] = field(default_factory=list)
    realized: Decimal = ZERO
    dividends: Decimal = ZERO
    interest: Decimal = ZERO
    fees: Decimal = ZERO

    def value(self, marks: dict[str, Decimal]) -> Decimal:
        return self.cash + sum((a for _, a, _, _ in self.receivables), ZERO) + sum((q * marks[i] for i, q in self.quantities.items() if q), ZERO)


@dataclass(frozen=True)
class ClockStep:
    at: datetime
    kind: str


@dataclass(frozen=True)
class VenueStep:
    kind: str
    payload: dict


class PortfolioSimulation:
    def __init__(self, build: str, *, venue: str):
        self.build, self.venue = build, venue

    def steps(self, request: ReplayRequest):
        if not isinstance(request.spec.rules, (TrendRules, GuidanceRules)):
            raise EngineUnavailable("Unsupported research strategy rules")
        dataset, spec, scenario = request.dataset, request.spec, request.scenario
        ids = sorted(i.instrument_id for i in spec.universe)
        sessions = dataset.sessions
        selected = [i for i, s in enumerate(sessions) if request.start <= s.date <= request.end]
        if not selected:
            raise EngineUnavailable("The evaluation period has no trading sessions")
        if request.start > request.end:
            raise ValueError("evaluation dates are reversed")
        bars = {(b.instrument_id, b.session): b for b in dataset.bars}
        account = Account(request.initial_capital_usd, dict.fromkeys(ids, 0), dict.fromkeys(ids, ZERO))
        events, fills, decisions, points = [], [], [], []
        pending: list[tuple[int, DecisionRecord, dict[str, int]]] = []
        guidance = GuidancePortfolio(dataset, spec, sessions[selected[0]].opens_at, selected[-1]) if isinstance(spec.rules, GuidanceRules) and request.control == "strategy" else None
        guidance_events = []
        # Publication, receipt, financial processing and model completion may
        # occur after the close. Wake then so an after-hours release can reach
        # the next opening window, without moving a close-time signal backward.
        wakes = sorted({row.availability.available_at + timedelta(seconds=spec.rules.decision_latency_seconds)
            for row in [*dataset.guidance_notices, *dataset.financials, *dataset.evidence]}) if guidance else []
        retired = set()
        peak = request.initial_capital_usd
        paused = False
        prior_day = sessions[selected[0]].date
        actions = {}
        for action in dataset.actions:
            if action.instrument_id in ids:
                actions.setdefault(action.effective_session, []).append(action)

        def event(at, kind, detail, instrument=None, amount=ZERO):
            events.append(AccountingEvent(at=at, kind=kind, detail=detail, instrument_id=instrument, amount_usd=amount))

        def settle(at):
            remaining = []
            for action_id, amount, payable, instrument in account.receivables:
                if payable is not None and payable <= at:
                    account.cash += amount
                    yield VenueStep("payment", {"action_id": action_id, "amount": amount})
                    event(payable, "payment", f"Settled receivable {action_id}", instrument, amount)
                else:
                    remaining.append((action_id, amount, payable, instrument))
            account.receivables = remaining

        def breaches(cash, quantities, marks, equity):
            if equity <= 0:
                return ["nonpositive equity"]
            result = []
            if cash < spec.risk.cash_reserve_fraction * equity:
                result.append("cash reserve")
            groups = {}
            for instrument in spec.universe:
                value = quantities[instrument.instrument_id] * marks.get(instrument.instrument_id, ZERO)
                if value > spec.risk.max_position_fraction * equity:
                    result.append(f"position:{instrument.instrument_id}")
                groups[instrument.risk_group] = groups.get(instrument.risk_group, ZERO) + value
            result.extend(f"group:{group}" for group, value in sorted(groups.items()) if value > spec.risk.max_group_fraction * equity)
            return result

        for index in selected:
            session = sessions[index]
            yield ClockStep(session.opens_at, "open")
            elapsed = (session.date - prior_day).days
            interest = account.cash * request.cash_annual_yield_fraction * D(elapsed) / D(365)
            account.cash += interest
            account.interest += interest
            yield VenueStep("cash_yield", {"rate": request.cash_annual_yield_fraction, "days": elapsed, "amount": interest})
            if interest:
                event(session.opens_at, "cash_yield", f"Simple ACT/365 cash yield over {elapsed} calendar days", amount=interest)
            prior_day = session.date
            # Corporate actions are economic events, independent of a strategy's
            # decision schedule. Late action metadata is not silently backdated.
            for action in sorted(actions.get(session.date, []), key=lambda a: (a.kind != "split", a.action_id)):
                instrument = action.instrument_id
                quantity = account.quantities[instrument]
                if action.available_at > session.opens_at:
                    raise EngineUnavailable(f"Corporate action {action.action_id} was unavailable at its effective open")
                yield VenueStep("action", {"action": action, "bar": bars.get((instrument, session.date))})
                if action.kind == "split":
                    ratio = action.split_ratio
                    if instrument in account.marks:
                        account.marks[instrument] /= ratio
                    for _, _, targets in pending:
                        if instrument in targets:
                            targets[instrument] = whole(D(targets[instrument]) * ratio)
                    exact = quantity * ratio
                    remaining = whole(exact)
                    fraction = exact - remaining
                    if quantity:
                        if fraction:
                            bar = bars.get((instrument, session.date))
                            if bar is None:
                                raise EngineUnavailable("Fractional split compensation requires an opening price")
                            released_basis = account.basis[instrument] * fraction / exact
                            payment = fraction * bar.open
                            account.cash += payment
                            account.basis[instrument] -= released_basis
                            account.realized += payment - released_basis
                            event(session.opens_at, "cash_in_lieu", "Fractional share paid at the opening price; explicit simulation assumption", instrument, payment)
                        account.quantities[instrument] = remaining
                        event(session.opens_at, "split", f"{quantity} shares × {ratio}; {remaining} whole shares retained", instrument)
                else:
                    amount = quantity * action.cash_per_share_usd
                    if quantity:
                        account.receivables.append((action.action_id, amount, action.payable_at, instrument))
                        if action.kind == "dividend":
                            account.dividends += amount
                        else:
                            account.realized += amount - account.basis[instrument]
                            account.quantities[instrument], account.basis[instrument] = 0, ZERO
                        event(session.opens_at, action.kind, "Cash entitlement recorded; unknown payment date remains a receivable", instrument, amount)
                    if action.kind == "delisting":
                        retired.add(instrument)
                        for _, _, targets in pending:
                            targets[instrument] = 0
            yield from settle(session.opens_at)
            opening_marks = dict(account.marks)
            missing_opens = set()
            for instrument in ids:
                bar = bars.get((instrument, session.date))
                if bar is not None:
                    opening_marks[instrument] = bar.open
                elif account.quantities[instrument]:
                    missing_opens.add(instrument)
            opening_equity = account.value(opening_marks)
            peak = max(peak, opening_equity)
            if 1 - opening_equity / peak >= spec.risk.max_drawdown_fraction and not paused:
                paused = True
                event(session.opens_at, "risk_pause", "Drawdown limit reached; new entries stop, reductions remain permitted")
            # One-session orders expire after this window. A subsequent weekly
            # target is a new decision, never an invisible retry of an old order.
            due = [p for p in pending if p[0] == index]
            pending = [p for p in pending if p[0] > index]
            for _, decision, targets in due:
                changes = {i: targets.get(i, account.quantities[i]) - account.quantities[i] for i in ids}
                turnover = ZERO
                # Sells precede buys, in stable identifier order.
                for instrument in sorted(ids, key=lambda i: (changes[i] >= 0, i)):
                    quantity = changes[instrument]
                    if not quantity:
                        continue
                    bar = bars.get((instrument, session.date))
                    reason = None
                    if decision.at >= session.opens_at:
                        raise ValueError("signal must precede its execution window")
                    if instrument in retired or bar is None or bar.volume == 0 or dataset.symbol_at(instrument, session.opens_at) is None:
                        reason = "No tradable opening bar/security mapping"
                    elif quantity > 0 and (paused or missing_opens):
                        reason = "Entries paused or another holding lacks an opening valuation"
                    if reason:
                        event(session.opens_at, "unfilled", f"{decision.decision_id}: {quantity} shares; {reason}", instrument)
                        continue
                    slip = bar.open * scenario.slippage_bps / D(10000)
                    price = bar.open + (slip if quantity > 0 else -slip)
                    fee = scenario.fee_for_fill(quantity, price)
                    gross = abs(quantity) * price
                    current_equity = account.value(opening_marks)
                    resulting_cash = account.cash - quantity * price - fee
                    resulting_quantities = dict(account.quantities)
                    resulting_quantities[instrument] += quantity
                    resulting_equity = current_equity - abs(quantity) * slip - fee
                    if resulting_cash < 0 or resulting_quantities[instrument] < 0:
                        reason = "Insufficient cash or shares after exact fees"
                    elif turnover + gross > opening_equity * spec.risk.max_turnover_fraction:
                        reason = "Execution window turnover limit"
                    elif quantity > 0 and breaches(resulting_cash, resulting_quantities, opening_marks, resulting_equity):
                        reason = "Exact proposed fill would breach a portfolio cap or cash reserve"
                    if reason:
                        event(session.opens_at, "unfilled", f"{decision.decision_id}: {quantity} shares; {reason}", instrument)
                        continue
                    receipt = yield VenueStep("order", {"instrument": instrument, "quantity": quantity, "price": price, "fee": fee, "decision_id": decision.decision_id, "at": session.opens_at})
                    if receipt is not None:
                        if receipt["quantity"] != quantity or abs(receipt["price"] - price) > D("0.00000001") or abs(receipt["fee"] - fee) > D("0.00000001"):
                            raise EngineUnavailable("Venue receipt differs from the declared whole-order fill model")
                        price, fee = receipt["price"], receipt["fee"]
                        gross = abs(quantity) * price
                        resulting_cash = account.cash - quantity * price - fee
                    realized = ZERO
                    if quantity < 0:
                        released = account.basis[instrument] * D(-quantity) / account.quantities[instrument]
                        account.basis[instrument] -= released
                        realized = -quantity * price - released
                        account.realized += realized
                    else:
                        account.basis[instrument] += quantity * price
                    account.quantities = resulting_quantities
                    account.cash = resulting_cash
                    account.fees += fee
                    turnover += gross
                    fills.append(Fill(fill_id=f"fill-{len(fills) + 1}", decision_id=decision.decision_id, instrument_id=instrument,
                        signal_at=decision.at, executed_at=session.opens_at, observed_at=bar.available_at,
                        quantity=quantity, price_usd=price, fee_usd=fee, slippage_usd=abs(quantity) * slip, realized_pnl_usd=realized))
                    if guidance:
                        guidance.filled(instrument, quantity, account.quantities[instrument], index, decision.entry_notice_ids.get(instrument))
            yield ClockStep(session.closes_at, "close")
            # Truth valuation can use this session's close; the signal still sees
            # it only at available_at. Stale marks are disclosed and block promotion.
            stale = []
            for instrument in ids:
                bar = bars.get((instrument, session.date))
                if bar is not None:
                    account.marks[instrument] = bar.close
                elif account.quantities[instrument] and instrument not in retired:
                    stale.append(instrument)
            yield from settle(session.closes_at)
            equity = account.value(account.marks)
            if equity <= 0:
                raise ValueError("Account equity became nonpositive")
            peak = max(peak, equity)
            if 1 - equity / peak >= spec.risk.max_drawdown_fraction and not paused:
                paused = True
                event(session.closes_at, "risk_pause", "Drawdown limit reached; new entries stop, reductions remain permitted")
            market_value = sum((q * account.marks[i] for i, q in account.quantities.items() if q), ZERO)
            basis = sum(account.basis.values(), ZERO)
            unrealized = market_value - basis
            expected_equity = request.initial_capital_usd + account.realized + unrealized + account.dividends + account.interest - account.fees
            if abs(equity - expected_equity) > D("0.00000001"):
                raise ArithmeticError("Equity did not reconcile to the independent P&L identity")
            points.append(EquityPoint(at=session.closes_at, equity_usd=equity, cash_usd=account.cash,
                receivables_usd=sum((a for _, a, _, _ in account.receivables), ZERO), market_value_usd=market_value,
                cost_basis_usd=basis, realized_pnl_usd=account.realized, unrealized_pnl_usd=unrealized,
                dividends_usd=account.dividends, cash_yield_usd=account.interest, fees_usd=account.fees,
                quantities=dict(account.quantities), stale_instruments=stale,
                risk_breaches=breaches(account.cash, account.quantities, account.marks, equity)))
            yield VenueStep("checkpoint", {"point": points[-1]})
            # Use the declared session calendar, not Friday arithmetic (holidays
            # and shortened trading weeks work without inventing missing sessions).
            next_session = sessions[index + 1] if index + 1 < len(sessions) else None
            last_week_session = next_session is not None and session.date.isocalendar()[:2] != next_session.date.isocalendar()[:2]
            if request.control == "cash" or (request.control == "equity_reference" and decisions):
                continue
            close_at = session.closes_at + timedelta(seconds=spec.rules.decision_latency_seconds)
            if request.control != "equity_reference" and not guidance and not last_week_session and not (isinstance(spec.rules, GuidanceRules) and index == selected[0]):
                continue
            execution_index = index + 1 + scenario.execution_delay_sessions
            execution = sessions[execution_index] if execution_index < len(sessions) and sessions[execution_index].date <= request.end else None
            times = [close_at]
            if guidance and next_session is not None:
                times.extend(at for at in wakes if close_at < at < next_session.opens_at and at.date() <= request.end)
            for at in times:
                yield ClockStep(at, "decision")
                selection = None
                if guidance:
                    pending_entries = {i for _, row, targets in pending for i in row.entry_notice_ids if i in targets}
                    pending_exits = {i for _, row, targets in pending for i in row.exit_reasons if i in targets}
                    selection = guidance.select(at, index+1, execution_index, account.quantities, pending_entries, pending_exits, retired)
                    guidance_events.extend(selection.events)
                    for _, row, targets in pending:
                        for instrument in selection.cancel_entries & row.entry_notice_ids.keys() & targets.keys():
                            targets.pop(instrument)
                            event(at, "order_cancelled", f"{row.decision_id}: later guidance invalidated the pending entry", instrument)
                    target = selection.target
                elif request.control == "equity_reference":
                    if len(ids) != 1:
                        raise ValueError("Equity reference requires one frozen instrument")
                    current = bars.get((ids[0], session.date))
                    known = current is not None and current.available_at <= at and dataset.symbol_at(ids[0], at) is not None
                    target = TargetDecision(status="targets", reason="Predeclared buy-and-hold equity reference", weights={ids[0]: request.reference_allocation_fraction}) if known else TargetDecision(status="no_signal", reason="Equity reference lacks its initial available close or security mapping")
                elif isinstance(spec.rules, TrendRules):
                    target = trend_targets(dataset, spec, at, control=request.control == "fixed_basket")
                else:
                    liquid = all(liquidity_check(dataset, i, at, spec.rules)[0] for i in ids)
                    target = TargetDecision(status="targets", reason="Guidance universe fixed-basket control", weights=cap_weights(dict.fromkeys(ids, D(1)), spec)) if liquid else TargetDecision(status="no_signal", reason="Missing fixed-basket liquidity history")
                proposed = {}
                if target.status == "targets":
                    # Quantity sizing sees only then-available marks. Pure exits
                    # need no estimate of current equity and can still reduce an
                    # unpriced holding at a later tradable opening window.
                    yield from settle(at)
                    positive = {i for i, weight in target.weights.items() if weight > 0}
                    required_marks = positive | {i for i in ids if account.quantities[i]}
                    known_marks = {i: next((b.close for b in reversed(dataset.bars) if b.instrument_id == i and b.available_at <= at), None) for i in required_marks}
                    if positive and any(value is None for value in known_marks.values()):
                        target = TargetDecision(status="no_signal", reason="No available mark for exact quantity sizing")
                    else:
                        known_equity = account.value(known_marks) if positive else ZERO
                        proposed = {i: whole(known_equity * weight / known_marks[i]) if weight else 0 for i, weight in target.weights.items()}
                if guidance and not proposed and not selection.events:
                    continue
                row = DecisionRecord(decision_id=f"decision-{len(decisions) + 1}", at=at,
                    intended_execution_at=execution.opens_at if execution else None, decision=target, proposed_quantities=proposed,
                    entry_notice_ids=selection.entries if selection else {}, exit_reasons=selection.exits if selection else {})
                decisions.append(row)
                if proposed and execution is not None:
                    if at >= execution.opens_at:
                        raise EngineUnavailable("Declared decision latency overlaps the execution window")
                    pending.append((execution_index, row, dict(proposed)))
                    if guidance:
                        guidance.submitted(selection.entries)
        limitations = [
            self.venue,
            "Quantities fixed at the decision; next-session opening price plus adverse slippage; exact-risk violations reject whole orders",
            "No intraday path, auction queue, spread dynamics or participation model; orders expire after one execution window",
            "Whole shares, zero leverage; market drift can breach caps between rebalances and is reported",
            "Cash yield is a declared simple ACT/365 assumption; taxes and settlement buying-power restrictions are excluded",
            "Dividends accrue as receivables at entitlement; only explicit payment dates make them spendable",
            "Split fractional shares receive opening-price cash compensation; source factor precision is preserved",
        ]
        if guidance:
            limitations.extend([
                "Guidance arms keep equal predeclared universe allocations; filtered-out weights remain cash, with no pyramiding or automatic entry retries",
                "Holding clocks start at actual entry fills; full entry/holding/delayed-exit horizons are purged at partition boundaries",
                "Intraday disclosures are evaluated after the close; after-hours source/evidence arrival can reach the next opening window",
                "Historical model classifications are exploratory and may contain training-data contamination; fixture outputs are hand-authored, not model observations",
            ])
        if request.control == "equity_reference":
            limitations.append("Equity reference fixes whole-share quantity from the first evaluated available close, attempts one later opening purchase, then holds without dividend reinvestment or rebalancing. Unfilled entry is reported, never resized or retried; remaining capital earns the declared cash yield. Return differences are not risk-adjusted alpha.")
        return ReplayResult(engine_build=self.build, control=request.control, initial_capital_usd=request.initial_capital_usd,
            decisions=decisions, fills=fills, events=sorted(events, key=lambda e: e.at), equity=points, limitations=limitations, guidance_events=guidance_events)
