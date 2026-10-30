"""Notice-level attribution of actual simulated fills, including unselected events.

This is an accounting comparison, not a counterfactual event study or an
independent-sample significance test. Cash yield and model costs stay separate.
"""
from dataclasses import dataclass, field
from decimal import Decimal as D, localcontext
from zoneinfo import ZoneInfo

from tradingagents.research.contracts import Contract, Digest, content_hash

ZERO = D(0)
TOLERANCE = D("0.00000001")
PAGE_SIZE = 50


class PairedEventSummary(Contract):
    artifact_hash: Digest
    page_artifact_hashes: list[Digest]
    events: int
    issuer_period_clusters: int
    both_entered: int
    challenger_only: int
    control_only: int
    neither_entered: int
    reconciled: bool
    challenger_event_pnl_usd: D
    control_event_pnl_usd: D
    event_pnl_difference_usd: D
    cash_yield_difference_usd: D
    portfolio_pnl_difference_usd: D
    method: str = "Pair every in-window notice, including repeats, abstentions and unfilled proposals. Attribute actual simulated fills and corporate actions to their entry notice. P&L differences include trading costs; account cash yield and model costs remain separate. These rows are dependent and are not a causal estimate or a win-probability forecast."


@dataclass
class Book:
    instrument_id: str
    quantity: int = 0
    basis: D = ZERO
    net_investment: D = ZERO
    realized: D = ZERO
    dividends: D = ZERO
    fees: D = ZERO
    slippage: D = ZERO
    entry_notional: D = ZERO
    entry_at: object = None
    exit_at: object = None
    held_closes: int = 0
    stale_closes: int = 0
    fills: list = field(default_factory=list)
    actions: list = field(default_factory=list)


def attribute_events(dataset, spec, run):
    with localcontext() as context:
        context.prec = 36
        return _attribute_events(dataset, spec, run)


def _attribute_events(dataset, spec, run):
    """Independently reconstruct notice ownership from saved fills and actions."""
    if run.control != "strategy" or not run.equity:
        raise ValueError("Paired event attribution requires a saved strategy equity path")
    ids = {i.instrument_id for i in spec.universe}
    notices = {n.notice_id: n for n in dataset.guidance_notices}
    decisions = {d.decision_id: d for d in run.decisions}
    calendar = {s.closes_at: s for s in dataset.sessions}
    selected = {calendar[p.at].date: calendar[p.at] for p in run.equity}
    bars = {(b.instrument_id, b.session): b for b in dataset.bars if b.instrument_id in ids and b.session in selected}
    books, active, marks = {}, {}, {}
    timeline = []
    for action in dataset.actions:
        if action.instrument_id in ids and action.effective_session in selected:
            at = selected[action.effective_session].opens_at
            if action.available_at > at:
                raise ValueError("Corporate action was unavailable at its effective open")
            timeline.append((at, 0, (action.kind != "split", action.action_id), "action", action))
    timeline.extend((fill.executed_at, 1, (index,), "fill", fill) for index, fill in enumerate(run.fills))
    timeline.extend((point.at, 2, (index,), "valuation", point) for index, point in enumerate(run.equity))
    for at, _, _, kind, item in sorted(timeline, key=lambda row: row[:3]):
        if kind == "action":
            instrument = item.instrument_id
            notice_id = active.get(instrument)
            if item.kind == "split" and instrument in marks:
                marks[instrument] /= item.split_ratio
            if notice_id is None:
                continue
            book = books[notice_id]
            detail = {"action_id": item.action_id, "kind": item.kind, "at": at.isoformat()}
            if item.kind == "split":
                exact = D(book.quantity) * item.split_ratio
                remaining = int(exact)
                fraction = exact - remaining
                if fraction:
                    bar = bars.get((instrument, item.effective_session))
                    if bar is None:
                        raise ValueError("Fractional compensation has no observed opening price")
                    released = book.basis * fraction / exact
                    compensation = fraction * bar.open
                    book.basis -= released
                    book.realized += compensation - released
                    book.net_investment += compensation
                    detail["cash_in_lieu_usd"] = str(compensation)
                book.quantity = remaining
                detail.update(ratio=str(item.split_ratio), remaining_quantity=remaining)
            else:
                entitlement = book.quantity * item.cash_per_share_usd
                book.net_investment += entitlement
                detail.update(entitlement_usd=str(entitlement), payable_at=item.payable_at.isoformat() if item.payable_at else None)
                if item.kind == "dividend":
                    book.dividends += entitlement
                else:
                    book.realized += entitlement - book.basis
                    book.quantity, book.basis = 0, ZERO
            book.actions.append(detail)
            if book.quantity == 0:
                book.exit_at = at
                active.pop(instrument)
        elif kind == "fill":
            fill = item
            if fill.instrument_id not in ids or fill.quantity == 0:
                raise ValueError("Fill does not belong to the frozen guidance universe")
            if fill.quantity > 0:
                if fill.realized_pnl_usd != 0:
                    raise ValueError("Entry fill cannot realize an existing event gain")
                notice_id = decisions[fill.decision_id].entry_notice_ids.get(fill.instrument_id)
                if notice_id not in notices or notices[notice_id].instrument_id != fill.instrument_id:
                    raise ValueError("Entry fill has no matching source notice")
                if fill.instrument_id in active or notice_id in books:
                    raise ValueError("Guidance attribution cannot silently pyramid or reuse an entry notice")
                book = books[notice_id] = Book(fill.instrument_id, entry_at=at)
                active[fill.instrument_id] = notice_id
                book.quantity = fill.quantity
                book.basis = book.entry_notional = fill.quantity * fill.price_usd
            else:
                notice_id = active.get(fill.instrument_id)
                if notice_id is None:
                    raise ValueError("Exit fill has no owned entry event")
                book = books[notice_id]
                if -fill.quantity > book.quantity:
                    raise ValueError("Exit exceeds the event's actual shares")
                released = book.basis * D(-fill.quantity) / book.quantity
                realized = -fill.quantity * fill.price_usd - released
                if abs(realized-fill.realized_pnl_usd) > TOLERANCE:
                    raise ValueError("Event sale basis differs from the saved fill ledger")
                book.realized += realized
                book.basis -= released
                book.quantity += fill.quantity
                if book.quantity == 0:
                    book.exit_at = at
                    active.pop(fill.instrument_id)
            book.net_investment -= fill.quantity * fill.price_usd + fill.fee_usd
            book.fees += fill.fee_usd
            book.slippage += fill.slippage_usd
            book.fills.append({**fill.model_dump(mode="json"),
                "exit_reason": decisions[fill.decision_id].exit_reasons.get(fill.instrument_id) if fill.quantity < 0 else None})
        else:
            point = item
            day = calendar[point.at].date
            for instrument in ids:
                bar = bars.get((instrument, day))
                if bar:
                    marks[instrument] = bar.close
                expected = books[active[instrument]].quantity if instrument in active else 0
                if point.quantities.get(instrument, 0) != expected:
                    raise ValueError("Event shares do not reconcile to saved account holdings")
                if instrument in active:
                    book = books[active[instrument]]
                    book.held_closes += 1
                    book.stale_closes += instrument in point.stale_instruments
    outcomes = {}
    event_total = ZERO
    for notice_id, book in books.items():
        value = book.quantity * marks[book.instrument_id] if book.quantity else ZERO
        pnl = book.net_investment + value
        if abs(pnl-(book.realized + value-book.basis + book.dividends-book.fees)) > TOLERANCE:
            raise ValueError("Event P&L identity failed")
        event_total += pnl
        outcomes[notice_id] = {"state": "open" if book.quantity else "closed", "entered": True,
            "entry_at": book.entry_at.isoformat(), "exit_at": book.exit_at.isoformat() if book.exit_at else None,
            "entry_notional_usd": str(book.entry_notional), "remaining_quantity": book.quantity,
            "realized_pnl_usd": str(book.realized), "unrealized_pnl_usd": str(value-book.basis),
            "dividends_usd": str(book.dividends), "fees_usd": str(book.fees), "slippage_usd": str(book.slippage),
            "investment_pnl_usd": str(pnl), "contribution_fraction": str(pnl/run.initial_capital_usd),
            "held_closes": book.held_closes, "stale_closes": book.stale_closes,
            "final_valuation_stale": bool(book.quantity and book.instrument_id in run.equity[-1].stale_instruments),
            "fills": book.fills, "corporate_actions": book.actions}
    last = run.equity[-1]
    investment_pnl = last.equity_usd-run.initial_capital_usd-last.cash_yield_usd
    if abs(event_total-investment_pnl) > TOLERANCE:
        raise ValueError("Event contributions plus cash yield do not reconcile to portfolio P&L")
    histories = {}
    for event in run.guidance_events:
        histories.setdefault(event.notice_id, []).append(event.model_dump(mode="json"))
    proposed = {notice for decision in run.decisions for instrument, notice in decision.entry_notice_ids.items()
                if decision.proposed_quantities.get(instrument, 0) > 0}
    for notice_id in histories.keys() | proposed:
        if notice_id not in outcomes:
            outcomes[notice_id] = empty_outcome("not_filled" if notice_id in proposed else "not_entered")
    for notice_id, outcome in outcomes.items():
        outcome["decisions"] = histories.get(notice_id, [])
        outcome["entry_proposed"] = notice_id in proposed
    return {"outcomes": outcomes, "event_pnl_usd": event_total, "cash_yield_usd": last.cash_yield_usd,
        "portfolio_pnl_usd": last.equity_usd-run.initial_capital_usd}


def empty_outcome(state="not_entered"):
    return {"state": state, "entered": False, "investment_pnl_usd": "0", "contribution_fraction": "0",
        "entry_notional_usd": "0", "remaining_quantity": 0, "entry_at": None, "exit_at": None,
        "fills": [], "corporate_actions": [], "decisions": [], "entry_proposed": False}


def paired_events(dataset, spec, challenger, control, *, start, end):
    with localcontext() as context:
        context.prec = 36
        return _paired_events(dataset, spec, challenger, control, start=start, end=end)


def _paired_events(dataset, spec, challenger, control, *, start, end):
    if challenger.initial_capital_usd != control.initial_capital_usd or [p.at for p in challenger.equity] != [p.at for p in control.equity]:
        raise ValueError("Paired outcomes require identical initial capital and evaluation sessions")
    left, right = attribute_events(dataset, spec, challenger), attribute_events(dataset, spec, control)
    ids = {i.instrument_id for i in spec.universe}
    notices = [n for n in dataset.guidance_notices if n.instrument_id in ids
        and (start <= n.availability.available_at.astimezone(ZoneInfo(dataset.timezone)).date() <= end
             or n.notice_id in left["outcomes"] or n.notice_id in right["outcomes"])]
    rows, clusters = [], set()
    counts = dict.fromkeys(("both_entered", "challenger_only", "control_only", "neither_entered"), 0)
    for notice in sorted(notices, key=lambda n: (n.availability.available_at, n.notice_id)):
        cluster = content_hash([notice.instrument_id, notice.period_start.isoformat(), notice.period_end.isoformat()])
        clusters.add(cluster)
        a, b = left["outcomes"].get(notice.notice_id, empty_outcome()), right["outcomes"].get(notice.notice_id, empty_outcome())
        counts["both_entered" if a["entered"] and b["entered"] else "challenger_only" if a["entered"] else "control_only" if b["entered"] else "neither_entered"] += 1
        difference = D(a["investment_pnl_usd"])-D(b["investment_pnl_usd"])
        rows.append({"notice_id": notice.notice_id, "instrument_id": notice.instrument_id, "cluster_id": cluster,
            "available_at": notice.availability.available_at.isoformat(), "period_start": notice.period_start.isoformat(),
            "period_end": notice.period_end.isoformat(), "challenger": a, "control": b,
            "pnl_difference_usd": str(difference), "contribution_difference_fraction": str(difference/challenger.initial_capital_usd),
            "matched_fill_times": bool(a["entered"] and b["entered"] and a["entry_at"] == b["entry_at"] and a["exit_at"] == b["exit_at"])})
    summary = {"events": len(rows), "issuer_period_clusters": len(clusters), **counts, "reconciled": True,
        "challenger_event_pnl_usd": str(left["event_pnl_usd"]), "control_event_pnl_usd": str(right["event_pnl_usd"]),
        "event_pnl_difference_usd": str(left["event_pnl_usd"]-right["event_pnl_usd"]),
        "cash_yield_difference_usd": str(left["cash_yield_usd"]-right["cash_yield_usd"]),
        "portfolio_pnl_difference_usd": str(left["portfolio_pnl_usd"]-right["portfolio_pnl_usd"])}
    return summary, rows


def save_paired_events(store, summary, rows, provenance):
    pages, artifacts = [], []
    for offset in range(0, len(rows), PAGE_SIZE):
        page = rows[offset:offset+PAGE_SIZE]
        digest = store.put_json({"schema_version": 1, "offset": offset, "rows": page})
        pages.append({"artifact_hash": digest, "offset": offset, "rows": len(page)})
        artifacts.append(digest)
    index = store.put_json({"schema_version": 1, "summary": summary, "provenance": provenance, "pages": pages,
        "limitations": ["Zero event contribution means no owned investment P&L; it is not a hypothetical return for an excluded trade.",
            "Slippage is already included in fill prices and is not subtracted again. Dividends and delisting proceeds accrue at entitlement, including unpaid receivables.",
            "Account cash yield and recurring model costs are separate from event trading P&L. Trade sizes and fill times may differ between arms.",
            "Repeated notices share issuer/forecast-period clusters. Do not treat rows as independent trials or infer causal selection skill.",
            "Closing marks follow the saved simulation's truth valuations; stale marks and open holdings remain explicit."]})
    return PairedEventSummary(artifact_hash=index, page_artifact_hashes=artifacts, **summary), [index, *artifacts]


def verify_paired_artifacts(report, artifacts, store):
    """Check that every page is pinned and accessible before publishing a job."""
    available = set(artifacts.values())
    runs = {(run["version_id"], run["scenario"]): run["artifact_hash"] for run in report["runs"] if run["control"] == "strategy"}
    for arm in report.get("arm_comparisons", []):
        summary = PairedEventSummary.model_validate(arm["paired_events"])
        if not {summary.artifact_hash, *summary.page_artifact_hashes}.issubset(available):
            raise ValueError("Paired event index or pages are missing from the published artifacts")
        index = store.json(summary.artifact_hash)
        if index.get("schema_version") != 1 or [page["artifact_hash"] for page in index["pages"]] != summary.page_artifact_hashes:
            raise ValueError("Paired page index differs from the pinned report")
        if index["summary"] != summary.model_dump(mode="json", exclude={"artifact_hash", "page_artifact_hashes", "method"}):
            raise ValueError("Paired index summary differs from the report")
        provenance = index["provenance"]
        if any(provenance[key] != arm[key] for key in ("challenger_version_id", "control_version_id", "scenario")) or any(
            provenance[f"{side}_run_hash"] != runs[arm[f"{side}_version_id"], arm["scenario"]] for side in ("challenger", "control")):
            raise ValueError("Paired events reference different strategy runs")
        offset, notices = 0, set()
        for page in index["pages"]:
            payload = store.json(page["artifact_hash"])
            rows = payload["rows"]
            if payload.get("schema_version") != 1 or page["offset"] != offset or payload["offset"] != offset or len(rows) != page["rows"] or not 0 < len(rows) <= PAGE_SIZE:
                raise ValueError("Paired page coverage is inconsistent")
            for row in rows:
                if row["notice_id"] in notices:
                    raise ValueError("Paired page repeats a notice")
                notices.add(row["notice_id"])
            offset += len(rows)
        if offset != summary.events:
            raise ValueError("Paired event pages do not cover the reported notices")
