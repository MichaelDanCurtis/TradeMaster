"""Prospective portfolio sizing using the same pure strategy kernel as replay.

This module has no account/broker, database, wall clock or approval authority.
Theoretical shares use the reviewed capital envelope and known raw prices.
Exact limit prices, cash constraints and human approval belong to execution.
"""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN

from tradingagents.research.contracts import StrategySpec, TrendRules, GuidanceRules
from tradingagents.research.data.contracts import DatasetBundle
from tradingagents.research.strategies.trend import trend_targets


def deployment_portfolio(dataset: DatasetBundle, spec: StrategySpec, as_of: datetime,
                         capital: Decimal, quantities: dict[str, Decimal], *, guidance_context=None) -> dict:
    if as_of.tzinfo is None:
        raise ValueError("Decision time must include a timezone")
    if capital <= 0 or any(q < 0 or q != q.to_integral_value() for q in quantities.values()):
        raise ValueError("The initial strategy requires positive funding and whole long shares")
    if set(quantities) != {i.instrument_id for i in spec.universe}:
        raise ValueError("Attributed holdings must cover the frozen instrument universe")
    result = {"status": "unavailable", "reason": "", "as_of": as_of.isoformat(),
              "capital_usd": str(capital), "holdings": {k: str(v) for k,v in quantities.items()},
              "portfolio": [], "decision": None, "execution_opens_at": None,
              "execution_deadline": None}
    completed = [s for s in dataset.sessions if s.closes_at <= as_of]
    future = [s for s in dataset.sessions if s.opens_at > as_of]
    if not completed or not future:
        result["reason"] = "Known calendar must include a completed session and the next execution session"
        return result
    previous, execution = completed[-1], future[0]
    trend=isinstance(spec.rules,TrendRules)
    if trend and as_of != previous.closes_at + timedelta(seconds=spec.rules.decision_latency_seconds):
        result["reason"] = "Trend decision time must equal the completed session close plus frozen latency"
        return result
    if trend and previous.date.isocalendar()[:2] == execution.date.isocalendar()[:2]:
        result.update(status="not_due", reason="The frozen weekly strategy is not due on this session")
        return result
    result.update(execution_opens_at=execution.opens_at.isoformat(),
                  execution_deadline=(execution.opens_at+timedelta(minutes=5)).isoformat())
    entries,exits={},{}
    if isinstance(spec.rules,GuidanceRules):
        from tradingagents.research.strategies.guidance_deployment import guidance_deployment_selection
        if as_of<previous.closes_at+timedelta(seconds=spec.rules.decision_latency_seconds):
            result["reason"]="Guidance cutoff precedes the completed close plus frozen latency"
            return result
        try:
            selected,state=guidance_deployment_selection(dataset,spec,as_of,execution,quantities,guidance_context)
        except ValueError as exc:
            result["reason"]=str(exc)
            return result
        decision=selected.target;entries=selected.entries;exits=selected.exits
        result.update(guidance_state=state,entry_notice_ids=entries,exit_reasons=exits,
                      cancel_entries=sorted(selected.cancel_entries),guidance_events=[e.model_dump(mode="json") for e in selected.events])
    else:
        decision = trend_targets(dataset, spec, as_of)
    result["decision"] = decision.model_dump(mode="json")
    if decision.status != "targets":
        result.update(status="no_signal" if not trend else "unavailable", reason=decision.reason)
        return result
    marks = {bar.instrument_id:bar for bar in dataset.bars
             if bar.session == previous.date and bar.available_at <= as_of}
    rows=[]
    for instrument in spec.universe:
        identifier=instrument.instrument_id
        symbol=dataset.symbol_at(identifier, as_of)
        # A known future symbol change needs a separate execution mapping review.
        # Never emit an old ticker or accept a mapping only learned after decision.
        if symbol != instrument.symbol or dataset.symbol_at(identifier,execution.opens_at) != symbol:
            result["reason"]="Security mapping changed; reconcile the frozen universe before trading"
            return result
        if identifier not in marks:
            result["reason"]="Missing available raw close for funded quantity sizing"
            return result
        price=marks[identifier].close
        current=int(quantities[identifier])
        weight=decision.weights.get(identifier)
        desired=current if weight is None else int((capital*weight/price).to_integral_value(rounding=ROUND_DOWN))
        rows.append({"instrument_id":identifier,"symbol":symbol,"risk_group":instrument.risk_group,
                     "weight":str(weight) if weight is not None else None,"reference_price_usd":str(price),
                     "reference_available_at":marks[identifier].available_at.isoformat(),
                     "current_quantity":current,"desired_quantity":desired,"delta_quantity":desired-current,
                     **({"entry_notice_id":entries.get(identifier),"exit_reason":exits.get(identifier)} if not trend else {})})
    result.update(status="targets",reason=decision.reason,portfolio=rows,
                  target_exposure_usd=str(sum((Decimal(r["desired_quantity"])*Decimal(r["reference_price_usd"]) for r in rows),Decimal(0))),
                  limitations=["Prices and covariance describe the decision snapshot, not future fills" if trend else "Reference prices describe the decision snapshot; guidance exits use actual-fill holding clocks",
                               "The execution window permits human submission during the first five minutes; delays and limits can differ from a next-open replay",
                               "Theoretical targets do not confer order approval or assume pending sale proceeds"])
    return result
