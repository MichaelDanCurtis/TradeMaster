"""Pure FIFO account reconciliation and exact flow-adjusted performance.

FIFO is an explicit analytical attribution convention, not a tax report or a
claim about a broker's cost-basis method. Broker cash/quantities/equity reconcile
independently. Missing flow valuations never become an estimated exact return.
"""
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal as D, localcontext

from tradingagents.research.account_rounding import equity_reconciles, equity_residual, rounding_record
from tradingagents.research.accounting_contracts import AccountActivity
from tradingagents.research.execution_contracts import PaperAccountSnapshot

ZERO = D(0)
TOLERANCE = D("0.000001")


@dataclass
class Lot:
    symbol: str
    quantity: D
    basis: D
    owner: str


def reconcile_account(baseline: PaperAccountSnapshot, snapshots: list[PaperAccountSnapshot], activities: list[AccountActivity], attribution: dict[str, str] | None = None) -> dict:
    with localcontext() as context:
        context.prec = 40
        return _reconcile(baseline, snapshots, activities, attribution or {})


def _reconcile(baseline, snapshots, activities, attribution):
    cash, external_flows, income, fees, realized = baseline.cash_usd, ZERO, ZERO, ZERO, ZERO
    lots = [Lot(p.symbol, p.quantity, p.cost_basis_usd, "legacy_manual") for p in baseline.positions if p.quantity]
    opening_unrealized = sum((p.market_value_usd-p.cost_basis_usd for p in baseline.positions), ZERO)
    owner_realized, owner_income, owner_fees = defaultdict(lambda: ZERO), defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    owner_cash = defaultdict(lambda: ZERO, {"unallocated_cash": baseline.cash_usd})
    cash_events = []
    owner_history = []
    order_weights = {}
    position_cycles = {}
    ownership = [(baseline.observed_at, _ownership(lots))]
    discrepancies, limitations, fills = [], ["FIFO analytical attribution; broker cost-basis conventions are reported separately"], []
    if not equity_reconciles(baseline):
        discrepancies.append({"code":"baseline_equity_mismatch", "detail":"Opening cash and positions do not reconcile to equity"})
    ordered = sorted(activities, key=lambda a:(a.effective_at, a.source_id))
    if len({a.source_id for a in ordered}) != len(ordered):
        raise ValueError("Ledger activities must have unique source IDs")
    points = sorted(snapshots, key=lambda s:s.observed_at)
    if not points or points[0].observed_at <= baseline.observed_at:
        raise ValueError("Reconciliation needs account observations after its baseline")
    identity = baseline.provider_id, baseline.account_id, baseline.evidence_kind
    if any((s.provider_id,s.account_id,s.evidence_kind) != identity for s in points):
        raise ValueError("Equity history changes account identity or evidence class")
    if len({s.observed_at for s in points}) != len(points):
        raise ValueError("Conflicting account observations share a timestamp")
    if any(a.effective_at <= baseline.observed_at or a.effective_at > points[-1].observed_at for a in ordered):
        raise ValueError("Ledger activity lies outside the baseline and observation window")
    by_time = defaultdict(list)
    for a in ordered: by_time[a.effective_at].append(a)
    # Without source sequence, simultaneous mixed corporate actions/fills are
    # ambiguous. Do not invent an economic ordering from opaque activity IDs.
    for at, group in by_time.items():
        symbols = {a.symbol for a in group if a.kind in {"split", "symbol_change"}}
        if any(a.symbol in symbols and a.kind == "fill" for a in group):
            discrepancies.append({"code":"ambiguous_activity_order", "detail":str(at)})
        for symbol in {a.symbol for a in group if a.kind=="fill"}:
            if {a.side for a in group if a.kind=="fill" and a.symbol==symbol}=={"buy","sell"}:
                discrepancies.append({"code":"ambiguous_fill_sequence","detail":str(at),"symbol":symbol})
    units, nav, high_nav, max_dd = baseline.equity_usd, D(1), D(1), ZERO
    return_known = not any(sum(a.kind in {"deposit", "withdrawal"} for a in group)>1 for group in by_time.values())
    if not return_known: limitations.append("Simultaneous external flows have no verified source ordering; exact return is unavailable")
    curve = [{"observed_at":baseline.observed_at.isoformat(), "equity_usd":baseline.equity_usd, "cash_usd":baseline.cash_usd,
        "net_external_flows_usd":ZERO, "investment_pnl_usd":ZERO, "time_weighted_return_fraction":ZERO, "drawdown_fraction":ZERO}]
    owner_history.append(_owner_point(baseline, lots, owner_cash))
    index = 0
    for snapshot in points:
        while index < len(ordered) and ordered[index].effective_at <= snapshot.observed_at:
            a = ordered[index]; index += 1
            owner = attribution.get(a.broker_order_id, "external_manual")
            cash_before = dict(owner_cash)
            weights = defaultdict(lambda: ZERO)
            if a.kind == "unknown":
                discrepancies.append({"code":"unknown_activity", "source_id":a.source_id, "detail":"Unsupported broker activity retained without a favorable cash assumption"})
                continue
            if a.kind == "fill":
                gross = a.quantity*a.price_usd
                if a.side == "buy":
                    if not any(lot.symbol==a.symbol and lot.owner==owner and lot.quantity>0 for lot in lots):
                        position_cycles[a.symbol,owner]={"symbol":a.symbol,"owner":owner,
                            "entry_source_id":a.source_id,"entry_broker_order_id":a.broker_order_id,
                            "entry_at":a.effective_at.isoformat()}
                    lots.append(Lot(a.symbol, a.quantity, gross, owner))
                    cash -= gross+a.fee_usd
                    owner_cash[owner] -= gross
                    weights[owner] = a.quantity
                else:
                    available = sum((lot.quantity for lot in lots if lot.symbol == a.symbol), ZERO)
                    if a.quantity > available:
                        discrepancies.append({"code":"unfunded_sell", "source_id":a.source_id, "detail":"Observed sell exceeds recorded long holdings"})
                        continue
                    pnl, weights = _consume(lots, a.symbol, a.quantity, gross)
                    for key, amount in pnl.items(): owner_realized[key] += amount
                    realized += sum(pnl.values(), ZERO)
                    cash += gross-a.fee_usd
                    _allocate(owner_cash, weights, gross)
                _allocate(owner_fees, weights, a.fee_usd)
                _allocate(owner_cash, weights, -a.fee_usd)
                fees += a.fee_usd
                order_weights.setdefault(a.broker_order_id, defaultdict(lambda: ZERO))
                for key, qty in weights.items(): order_weights[a.broker_order_id][key] += qty
                fills.append({"source_id":a.source_id, "broker_order_id":a.broker_order_id, "symbol":a.symbol, "side":a.side, "quantity":a.quantity,
                    "price_usd":a.price_usd, "fee_usd":a.fee_usd, "executor":owner, "position_owners":dict(weights), "effective_at":a.effective_at.isoformat()})
            elif a.kind in {"deposit", "withdrawal"}:
                cash += a.cash_amount_usd
                external_flows += a.cash_amount_usd
                owner_cash["unallocated_cash"] += a.cash_amount_usd
                if return_known:
                    if a.equity_before_flow_usd is None or a.time_precision != "instant":
                        return_known = False
                        limitations.append(f"Exact return/drawdown unavailable: flow {a.source_id} has no contemporaneous valuation")
                    else:
                        nav = a.equity_before_flow_usd/units
                        high_nav = max(high_nav, nav)
                        max_dd = max(max_dd, 1-nav/high_nav)
                        units += a.cash_amount_usd/nav
                        if units <= 0:
                            return_known = False
                            limitations.append("External withdrawal exhausts account units; a new reviewed observation period is required")
            elif a.kind in {"dividend", "interest"}:
                cash += a.cash_amount_usd
                income += a.cash_amount_usd
                owners = {}
                if a.kind == "dividend" and a.entitlement_at is not None and a.entitlement_at >= baseline.observed_at:
                    state = next((state for at,state in reversed(ownership) if at <= a.entitlement_at), {})
                    owners = state.get(a.symbol, {})
                if owners:
                    _allocate(owner_income, owners, a.cash_amount_usd)
                    _allocate(owner_cash, owners, a.cash_amount_usd)
                else:
                    owner_income["unattributed_income"] += a.cash_amount_usd
                    owner_cash["unattributed_income"] += a.cash_amount_usd
            elif a.kind == "fee":
                cash += a.cash_amount_usd
                fees -= a.cash_amount_usd
                weights = order_weights.get(a.broker_order_id, {"unattributed_fees":D(1)})
                _allocate(owner_fees, weights, -a.cash_amount_usd)
                _allocate(owner_cash, weights, a.cash_amount_usd)
            elif a.kind == "split":
                for lot in lots:
                    if lot.symbol == a.symbol: lot.quantity *= a.split_ratio
            elif a.kind == "cash_in_lieu":
                available = sum((lot.quantity for lot in lots if lot.symbol == a.symbol), ZERO)
                if a.quantity > available:
                    discrepancies.append({"code":"unfunded_cash_in_lieu", "source_id":a.source_id})
                    continue
                pnl, weights = _consume(lots, a.symbol, a.quantity, a.cash_amount_usd)
                _allocate(owner_cash, weights, a.cash_amount_usd)
                realized += sum(pnl.values(), ZERO)
                for key, amount in pnl.items(): owner_realized[key] += amount
                cash += a.cash_amount_usd
            elif a.kind == "symbol_change":
                for lot in lots:
                    if lot.symbol == a.symbol: lot.symbol = a.new_symbol
                for (symbol,key),cycle in list(position_cycles.items()):
                    if symbol==a.symbol:
                        position_cycles[a.new_symbol,key]={**cycle,"symbol":a.new_symbol}
                        del position_cycles[symbol,key]
            current_ownership=_ownership(lots)
            for symbol,key in list(position_cycles):
                if not current_ownership.get(symbol,{}).get(key,ZERO):
                    del position_cycles[symbol,key]
            if cash < -TOLERANCE:
                discrepancies.append({"code":"negative_ledger_cash", "source_id":a.source_id, "cash_usd":cash})
            ownership.append((a.effective_at, _ownership(lots)))
            movements = {key: owner_cash[key]-cash_before.get(key, ZERO) for key in set(owner_cash)|set(cash_before)
                         if owner_cash[key] != cash_before.get(key, ZERO)}
            cash_events.append({"source_id":a.source_id,"effective_at":a.effective_at.isoformat(),"time_precision":a.time_precision,"kind":a.kind,
                                "cash_movements":movements,"ownership":_ownership(lots)})
        holdings = _ownership(lots)
        broker_positions = {p.symbol:p for p in snapshot.positions if p.quantity}
        for symbol in set(holdings) | set(broker_positions):
            expected = sum(holdings.get(symbol, {}).values(), ZERO)
            actual = broker_positions[symbol].quantity if symbol in broker_positions else ZERO
            if abs(expected-actual) > D("0.000000001"):
                discrepancies.append({"code":"position_mismatch", "at":snapshot.observed_at.isoformat(), "symbol":symbol, "expected_quantity":expected, "observed_quantity":actual})
        if abs(cash-snapshot.cash_usd) > TOLERANCE:
            discrepancies.append({"code":"cash_mismatch", "at":snapshot.observed_at.isoformat(), "expected_usd":cash, "observed_usd":snapshot.cash_usd})
        observed_equity = snapshot.cash_usd + sum((p.market_value_usd for p in snapshot.positions), ZERO)
        if abs(sum(owner_cash.values(), ZERO)-cash) > TOLERANCE:
            discrepancies.append({"code":"owner_cash_partition_mismatch","at":snapshot.observed_at.isoformat()})
        if not equity_reconciles(snapshot):
            discrepancies.append({"code":"equity_mismatch", "at":snapshot.observed_at.isoformat(), "expected_usd":observed_equity, "observed_usd":snapshot.equity_usd})
        if not snapshot.complete:
            discrepancies.append({"code":"incomplete_snapshot", "at":snapshot.observed_at.isoformat()})
        if return_known:
            nav = snapshot.equity_usd/units
            high_nav = max(high_nav, nav)
            max_dd = max(max_dd, 1-nav/high_nav)
        curve.append({"observed_at":snapshot.observed_at.isoformat(), "equity_usd":snapshot.equity_usd, "cash_usd":snapshot.cash_usd,
            "net_external_flows_usd":external_flows, "investment_pnl_usd":snapshot.equity_usd-baseline.equity_usd-external_flows,
            "time_weighted_return_fraction":nav-1 if return_known and not discrepancies else None,
            "drawdown_fraction":1-nav/high_nav if return_known and not discrepancies else None})
        owner_history.append(_owner_point(snapshot, lots, owner_cash))
    closing = points[-1]
    marks = {p.symbol:p.market_value_usd/p.quantity for p in closing.positions if p.quantity}
    basis, owner_unrealized, positions = ZERO, defaultdict(lambda: ZERO), []
    for symbol, owners in _ownership(lots).items():
        position_basis = sum((lot.basis for lot in lots if lot.symbol == symbol), ZERO)
        basis += position_basis
        for lot in lots:
            if lot.symbol == symbol and symbol in marks: owner_unrealized[lot.owner] += lot.quantity*marks[symbol]-lot.basis
        positions.append({"symbol":symbol, "quantity":sum(owners.values(),ZERO), "analytical_basis_usd":position_basis,
            "broker_basis_usd":next((p.cost_basis_usd for p in closing.positions if p.symbol == symbol), None), "owners":owners})
    unrealized = sum(owner_unrealized.values(), ZERO)
    pnl = closing.equity_usd-baseline.equity_usd-external_flows
    identity_pnl = realized+unrealized-opening_unrealized+income-fees
    reporting_change = equity_residual(closing)-equity_residual(baseline)
    if abs(identity_pnl+reporting_change-pnl) > TOLERANCE:
        discrepancies.append({"code":"pnl_identity_mismatch", "expected_usd":identity_pnl, "observed_usd":pnl})
    owner_keys = set(owner_realized)|set(owner_unrealized)|set(owner_income)|set(owner_fees)
    owners = [{"owner":key, "realized_pnl_usd":owner_realized[key], "unrealized_pnl_usd":owner_unrealized[key],
        "income_usd":owner_income[key], "fees_usd":owner_fees[key],
        "period_pnl_usd":owner_realized[key]+owner_unrealized[key]+owner_income[key]-owner_fees[key]-(opening_unrealized if key=="legacy_manual" else ZERO)} for key in sorted(owner_keys)]
    if any(equity_residual(s) for s in [baseline, *points]):
        limitations.append("Broker equity reporting residuals are shown separately; they are not attributed to strategy profit")
    if discrepancies:
        for point in curve: point["time_weighted_return_fraction"] = point["drawdown_fraction"] = point["investment_pnl_usd"] = None
    return {"reconciled":not discrepancies, "baseline_at":baseline.observed_at.isoformat(), "observed_at":closing.observed_at.isoformat(),
        "equity_usd":closing.equity_usd, "cash_usd":cash, "net_external_flows_usd":external_flows, "investment_pnl_usd":pnl if not discrepancies else None,
        "unexplained_equity_change_usd":pnl if discrepancies else None,
        "reporting_rounding_change_usd":reporting_change,
        "reporting_rounding_history":[rounding_record(s) for s in [baseline, *points]],
        "realized_pnl_usd":realized, "unrealized_pnl_usd":unrealized, "opening_unrealized_pnl_usd":opening_unrealized, "income_usd":income, "fees_usd":fees,
        "time_weighted_return_fraction":nav-1 if return_known and not discrepancies else None,
        "drawdown_fraction":1-nav/high_nav if return_known and not discrepancies else None,
        "maximum_drawdown_fraction":max_dd if return_known and not discrepancies else None,
        "return_method":"unitized_at_observed_external_flow_valuations", "drawdown_scope":"observed_since_reviewed_baseline",
        "positions":positions, "position_cycles":list(position_cycles.values()), "attribution":owners, "fills":fills, "equity_history":curve,
        "owner_equity_history":owner_history,"owner_cash_events":cash_events,
        "discrepancies":discrepancies, "limitations":limitations}


def _owner_point(snapshot, lots, cash):
    marks = {p.symbol:p.market_value_usd/p.quantity for p in snapshot.positions if p.quantity}
    owners = {key:{"cash_without_allocations_usd":value,"market_value_usd":ZERO,"quantities":{},"marks_complete":True}
              for key,value in cash.items()}
    for lot in lots:
        if not lot.quantity: continue
        owner = owners.setdefault(lot.owner,{"cash_without_allocations_usd":ZERO,"market_value_usd":ZERO,"quantities":{},"marks_complete":True})
        owner["quantities"][lot.symbol] = owner["quantities"].get(lot.symbol,ZERO)+lot.quantity
        if lot.symbol not in marks: owner["marks_complete"] = False
        else: owner["market_value_usd"] += lot.quantity*marks[lot.symbol]
    for owner in owners.values():
        owner["equity_without_allocations_usd"] = owner["cash_without_allocations_usd"]+owner["market_value_usd"] if owner["marks_complete"] else None
    return {"observed_at":snapshot.observed_at.isoformat(),"owners":owners}


def _ownership(lots):
    result = {}
    for lot in lots:
        if lot.quantity:
            owners = result.setdefault(lot.symbol, {})
            owners[lot.owner] = owners.get(lot.owner, ZERO)+lot.quantity
    return result


def _allocate(destination, weights, amount):
    total = sum(weights.values(), ZERO)
    if not total:
        destination["unattributed"] += amount
        return
    assigned = ZERO
    for index, (owner, weight) in enumerate(sorted(weights.items())):
        value = amount-assigned if index == len(weights)-1 else amount*weight/total
        destination[owner] += value
        assigned += value


def _consume(lots, symbol, quantity, proceeds):
    remaining, pnl, weights = quantity, defaultdict(lambda: ZERO), defaultdict(lambda: ZERO)
    for lot in lots:
        if lot.symbol != symbol or lot.quantity <= 0 or remaining <= 0: continue
        used = min(remaining, lot.quantity)
        basis = lot.basis*used/lot.quantity
        pnl[lot.owner] += proceeds*used/quantity-basis
        weights[lot.owner] += used
        lot.quantity -= used; lot.basis -= basis; remaining -= used
    return pnl, weights
