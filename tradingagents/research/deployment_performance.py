"""Deployment cash allocations and performance derived from reconciled ownership.

Allocations are internal analytical transfers, not broker deposits. A nominal
execution envelope is distinct from the deployment's changing marked equity.
"""
from datetime import datetime, timedelta
from decimal import Decimal as D, localcontext
from hashlib import sha256
from pathlib import Path

from sqlalchemy import text
from sqlmodel import select

from tradingagents.research.contracts import content_hash
from tradingagents.research.deployment_models import DeploymentCapitalFlow, StrategyDeploymentRecord
from tradingagents.research.accounting_models import PaperReconciliationRecord, PaperEnrollmentRecord
from tradingagents.research.repository import ConflictError, require
from tradingagents.ui.models import now_utc

ZERO = D(0)
BUILD = sha256(Path(__file__).read_bytes()).hexdigest()
EMPTY = {"cash_without_allocations_usd":"0", "market_value_usd":"0", "equity_without_allocations_usd":"0", "quantities":{}, "marks_complete":True}


def flows_for(session, identifier):
    rows = list(session.exec(select(DeploymentCapitalFlow).where(DeploymentCapitalFlow.deployment_id==identifier)
        .order_by(DeploymentCapitalFlow.effective_at,DeploymentCapitalFlow.revision)))
    for row in rows:
        if content_hash(row.payload) != row.content_hash:
            raise ConflictError("Deployment allocation history failed integrity verification")
    return rows


def allocation_state(session, record, receipt):
    if not receipt.report.get("reconciled") or "owner_equity_history" not in receipt.report:
        raise ConflictError("Reconcile the account with ownership cash history before reviewing deployment funding")
    rows = flows_for(session,record.deployment_id)
    if any(row.effective_at>receipt.observed_at for row in rows):
        raise ConflictError("Account observation precedes a deployment allocation; reconcile again")
    owner = receipt.report["owner_equity_history"][-1]["owners"].get(f"deployment:{record.deployment_id}",EMPTY)
    if not owner["marks_complete"]:
        raise ConflictError("Deployment funding requires complete owned-position marks")
    if record.active_terms_id and not rows:
        raise ConflictError("Existing deployment has no reviewed allocation baseline; its historical funding cannot be inferred")
    net = sum((D(row.amount_usd) for row in rows),ZERO)
    return {"net_allocations_usd":str(net),"cash_usd":str(net+D(owner["cash_without_allocations_usd"])),
        "market_value_usd":str(owner["market_value_usd"]),"equity_usd":str(net+D(owner["equity_without_allocations_usd"])),
        "investment_pnl_usd":str(owner["equity_without_allocations_usd"])}


def allocation_proposal(session, record, receipt, capital, *, retire=False):
    state = allocation_state(session,record,receipt)
    rebalance = retire or record.active_terms_id != record.pending_terms_id
    amount = (ZERO if retire else capital)-D(state["equity_usd"]) if rebalance else ZERO
    if amount<0 and -amount>D(state["cash_usd"]):
        raise ConflictError("Funding reduction exceeds deployment cash; reconcile exits before releasing capital")
    return {**state,"amount_usd":str(amount),"target_capital_usd":str(ZERO if retire else capital),
        "creates_flow":rebalance,"allocation_method":"internal_cash_transfer_at_approval",
        "scope":"Analytical allocation within this paper account; no broker deposit or withdrawal",
        "valuation_policy":"Exact flow-adjusted return requires a contemporaneous owned-position valuation; cash-only flows need no price estimate"}


def record_allocation(session, record, proposal, receipt, actor, action, *, review_id=None):
    if not proposal["creates_flow"]: return None
    at = now_utc()
    payload = {"deployment_id":record.deployment_id,"account_key":record.account_key,"revision":record.revision,
        "action":action,"amount_usd":proposal["amount_usd"],"terms_id":record.active_terms_id or record.pending_terms_id,
        "reconciliation_id":receipt.reconciliation_id,"review_id":review_id,"actor":actor,
        "effective_at":at.isoformat(),"reviewed_valuation_at":receipt.observed_at.isoformat(),"reviewed_allocation":proposal}
    row = DeploymentCapitalFlow(**{key:payload[key] for key in ("deployment_id","account_key","revision","action","amount_usd","terms_id","reconciliation_id","review_id","actor")},
        effective_at=at,payload=payload,content_hash=content_hash(payload))
    session.add(row)
    return row


def deployment_performance(report: dict, flows: list[dict], owner: str) -> dict:
    with localcontext() as context:
        context.prec=40
        return _performance(report,flows,owner)


def _performance(report,flows,owner):
    limitations=["Internal allocation accounting, not a separate broker account",
        "Returns include attributed fills, fees and entitled income; unallocated account interest and fees stay separate",
        "Drawdown is observed at saved valuations, not an intraday loss guarantee"]
    if report.get("source_corrections",{}).get("excluded_observation_ids"):
        limitations.append("Reviewed source corrections exclude affected historical account marks; original receipts remain available and replacement valuations are not inferred")
    unavailable={"status":"unavailable","equity_history":[],"capital_flows":flows,"limitations":limitations,
        "equity_usd":None,"cash_usd":None,"market_value_usd":None,"investment_pnl_usd":None,
        "time_weighted_return_fraction":None,"drawdown_fraction":None,"maximum_drawdown_fraction":None}
    if not report.get("reconciled"):
        limitations.append("Account discrepancies prevent deployment performance claims")
        return unavailable
    if "owner_equity_history" not in report or "owner_cash_events" not in report:
        limitations.append("Saved reconciliation predates ownership cash accounting; reconcile again")
        return unavailable
    if not flows:
        limitations.append("No approved deployment allocation history exists")
        return unavailable
    cutoff=datetime.fromisoformat(report["observed_at"])
    eligible=sorted((f for f in flows if datetime.fromisoformat(f["effective_at"])<=cutoff),key=lambda f:(datetime.fromisoformat(f["effective_at"]),f["revision"]))
    pending=[{**f,"exact_valuation":False,"awaiting_observation":True} for f in flows if datetime.fromisoformat(f["effective_at"])>cutoff]
    if not eligible:
        limitations.append("The allocation is newer than the saved account observation; reconcile again")
        return {**unavailable,"status":"awaiting_reconciliation"}
    start=datetime.fromisoformat(eligible[0]["effective_at"])
    points={datetime.fromisoformat(p["observed_at"]):p["owners"].get(owner,EMPTY) for p in report["owner_equity_history"]}
    events=sorted(report["owner_cash_events"],key=lambda e:datetime.fromisoformat(e["effective_at"]))
    by_time={}
    for flow in eligible: by_time.setdefault(datetime.fromisoformat(flow["effective_at"]),[]).append(flow)
    net=units=ZERO
    nav=high=D(1);max_dd=ZERO
    known=True;closed=False;history=[];valued_flows=[]
    def observe(equity):
        nonlocal nav,high,max_dd,known
        if units<=0 or equity<0:
            known=False
            return
        nav=equity/units;high=max(high,nav);max_dd=max(max_dd,1-nav/high)
    cursor=0;cash=ZERO;quantities={}
    timed_events=[(datetime.fromisoformat(e["effective_at"]),e) for e in events]
    for at in sorted(set(by_time)|{t for t in points if t>=start}):
        simultaneous=False
        while cursor<len(timed_events) and timed_events[cursor][0]<=at:
            event_at,event=timed_events[cursor];cursor+=1
            simultaneous=simultaneous or event_at==at
            cash+=D(event["cash_movements"].get(owner,"0"))
            quantities={symbol:D(owners.get(owner,"0")) for symbol,owners in event["ownership"].items() if D(owners.get(owner,"0"))}
        point=points.get(at)
        market=D(point["market_value_usd"]) if point and point["marks_complete"] else ZERO if not quantities else None
        before=net+cash+market if market is not None else None
        for flow in by_time.get(at,[]):
            amount=D(flow["amount_usd"])
            uncertain_day=any(e.get("time_precision")!="instant" and abs(event_at-at)<timedelta(days=1)
                and (D(e["cash_movements"].get(owner,"0")) or any(D(owners.get(owner,"0")) for owners in e["ownership"].values())) for event_at,e in timed_events)
            exact=before is not None and not simultaneous and not uncertain_day
            # First funding is valid only for an empty deployment book.
            if not history and not valued_flows:
                if amount<=0 or before!=0:
                    known=False;limitations.append("Opening allocation does not establish an empty positive funded book")
                else: units=amount
            elif known:
                if not exact or before<=0 or closed:
                    known=False;limitations.append("At least one funding change lacks an exact pre-flow valuation; dollar P&L is preserved")
                else:
                    observe(before)
                    units+=amount/nav
                    if abs(units)<D("1e-30"): units=ZERO;closed=True
                    elif units<0: known=False;limitations.append("Allocation withdrawal exceeds the deployment equity")
            net+=amount
            valued_flows.append({**flow,"equity_before_flow_usd":str(before) if exact else None,
                "exact_valuation":exact,"valuation_source":"reconciled_owned_positions" if point else "cash_only_book" if not quantities else "unavailable"})
            before=net+cash+market if market is not None else None
        if point or at in by_time:
            equity=net+cash+market if market is not None else None
            if known:
                if closed:
                    if equity!=0: known=False;limitations.append("Post-closure activity requires a new return period; residual cash and P&L remain attributed")
                elif equity is not None: observe(equity)
                else: known=False
            history.append({"observed_at":at.isoformat(),"equity_usd":str(equity) if equity is not None else None,
                "cash_usd":str(net+cash),"market_value_usd":str(market) if market is not None else None,
                "net_allocations_usd":str(net),"investment_pnl_usd":str(cash+market) if market is not None else None,
                "time_weighted_return_fraction":str(nav-1) if known else None,"drawdown_fraction":str(1-nav/high) if known else None,
                "source":"account_observation" if point else "capital_allocation"})
    latest=history[-1]
    if not known:
        # Do not present a usable chained history after one subperiod is missing.
        for point in history: point["time_weighted_return_fraction"]=point["drawdown_fraction"]=None
    if pending: limitations.append("New allocations await a later account reconciliation; displayed equity and returns stop at the saved observation")
    return {**latest,"status":"awaiting_reconciliation" if pending else "reconciled" if known else "return_unavailable","maximum_drawdown_fraction":str(max_dd) if known else None,
        "equity_history":history,"capital_flows":valued_flows+pending,"limitations":limitations,"closed":closed,
        "return_method":"unitized_at_exact_internal_allocation_valuations"}


def account_deployment_performance(sessions,key):
    with sessions() as session:
        session.execute(text("BEGIN"))
        require(session,PaperEnrollmentRecord,key)
        receipt=session.exec(select(PaperReconciliationRecord).where(PaperReconciliationRecord.account_key==key)
            .order_by(PaperReconciliationRecord.created_at.desc())).first()
        deployments=list(session.exec(select(StrategyDeploymentRecord).where(StrategyDeploymentRecord.account_key==key)))
        result=[]
        for record in deployments:
            flows=flows_for(session,record.deployment_id)
            wire=[{**f.payload,"flow_id":f.flow_id,"content_hash":f.content_hash} for f in flows]
            performance=deployment_performance(receipt.report if receipt else {},wire,f"deployment:{record.deployment_id}")
            result.append({"deployment_id":record.deployment_id,"name":record.name,"version_id":record.version_id,"state":record.state,
                "performance":performance,"input_hash":content_hash({"reconciliation":receipt.content_hash if receipt else None,
                    "report":content_hash(receipt.report) if receipt else None,"flows":[f.content_hash for f in flows],"build":BUILD})})
        return {"account_key":key,"reconciliation_id":receipt.reconciliation_id if receipt else None,
            "observed_at":receipt.observed_at.isoformat() if receipt else None,"calculation_build":BUILD,"deployments":result}
