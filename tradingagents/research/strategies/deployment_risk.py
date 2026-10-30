"""Descriptive risk of funded quantities at pinned decision prices.

Reconciled quantities may be observed after the decision cutoff. This is a
revaluation at decision prices, not contemporaneous account performance.
"""
from decimal import Decimal as D, localcontext, ROUND_DOWN

from tradingagents.research.contracts import TrendRules
from tradingagents.research.strategies.portfolio_risk import portfolio_risk


def _aligned_returns(dataset, spec, as_of, lookback):
    completed=[s for s in dataset.sessions if s.closes_at<=as_of]
    if len(completed)<lookback+1:
        raise ValueError(f"Need {lookback+1} completed sessions for this trailing risk window")
    dates=[s.date for s in completed[-lookback-1:]]
    bars={(b.instrument_id,b.session):b for b in dataset.bars if b.available_at<=as_of}
    actions={}
    for action in dataset.actions:
        if action.available_at<=as_of:
            actions.setdefault((action.instrument_id,action.effective_session),[]).append(action)
    returns={}
    for instrument in spec.universe:
        key=instrument.instrument_id
        if any((key,day) not in bars for day in dates):
            raise ValueError(f"Missing or late observation for {key}; covariance is unavailable")
        values=[]
        for previous,day in zip(dates,dates[1:]):
            split,dividend=D(1),D(0)
            for action in actions.get((key,day),[]):
                if action.kind=="split": split*=action.split_ratio
                elif action.kind=="dividend": dividend+=action.cash_per_share_usd
                elif action.kind=="delisting": raise ValueError("Delisting requires reconciled valuation before covariance reporting")
            values.append((bars[key,day].close+dividend)*split/bars[key,previous].close-1)
        returns[key]=values
    return returns,dates[1:]


def funded_portfolio_risk(dataset,spec,as_of,capital,quantities,*,basis,policy=None):
    if as_of.tzinfo is None:
        raise ValueError("Risk valuation time must include a timezone")
    if basis not in {"proposed_whole_shares","reconciled_holdings_at_decision_prices"}:
        raise ValueError("Unknown quantity basis")
    if not capital.is_finite() or capital<=0 or set(quantities)!={i.instrument_id for i in spec.universe}:
        raise ValueError("Positive funding and the complete frozen universe are required")
    if any(not q.is_finite() or q<0 for q in quantities.values()):
        raise ValueError("Risk quantities must be finite and long-only")
    policy=policy or spec.risk
    # Guidance has no volatility sizing parameter. Its fixed 63-session window
    # is descriptive only and does not affect event admission or target sizing.
    lookback=spec.rules.volatility_sessions if isinstance(spec.rules,TrendRules) else 63
    result={"schema_version":1,"basis":basis,"as_of":as_of.isoformat(),"capital_usd":str(capital),
        "lookback_return_sessions":lookback,"status":"unavailable","reason":"",
        "positions":[],"groups":[],"gross_exposure_usd":None,"unused_envelope_usd":None,
        "reserve_headroom_usd":None,"covariance":None,"annualized_volatility_usd":None,
        "capital_relative_volatility_fraction":None,"covariance_denominator_usd":None,
        "limitations":["Quantities are valued at available raw closing prices from the decision snapshot; these are not current broker marks or guaranteed fill prices.",
            "The committed nominal funding envelope is not measured deployment equity. Unused envelope is not settled cash or buying power.",
            "Pending orders, fees, execution gaps, liquidity and other account holdings are excluded from this descriptive estimate; exact-order checks remain authoritative."]}
    completed=[s for s in dataset.sessions if s.closes_at<=as_of]
    if not completed:
        result["reason"]="No completed decision session for valuation";return result
    marks={b.instrument_id:b for b in dataset.bars if b.session==completed[-1].date and b.available_at<=as_of}
    if any(i.instrument_id not in marks for i in spec.universe):
        result["reason"]="Missing available decision close; exposure cannot be valued";return result
    if any(dataset.symbol_at(i.instrument_id,as_of)!=i.symbol for i in spec.universe):
        result["reason"]="Security mapping differs from the frozen universe";return result
    exposures={i.instrument_id:quantities[i.instrument_id]*marks[i.instrument_id].close for i in spec.universe}
    gross=sum(exposures.values(),D(0));groups={}
    for instrument in spec.universe:
        key=instrument.instrument_id;value=exposures[key]
        groups[instrument.risk_group]=groups.get(instrument.risk_group,D(0))+value
        result["positions"].append({"instrument_id":key,"symbol":instrument.symbol,"quantity":str(quantities[key]),
            "price_usd":str(marks[key].close),"price_available_at":marks[key].available_at.isoformat(),
            "exposure_usd":str(value),"capital_fraction":str(value/capital),
            "limit_usd":str(capital*policy.max_position_fraction),"over_limit":value>capital*policy.max_position_fraction})
    result["groups"]=[{"group":key,"exposure_usd":str(value),"capital_fraction":str(value/capital),
        "limit_usd":str(capital*policy.max_group_fraction),"over_limit":value>capital*policy.max_group_fraction} for key,value in sorted(groups.items())]
    result.update(gross_exposure_usd=str(gross),unused_envelope_usd=str(capital-gross),
        reserve_headroom_usd=str(capital*(1-policy.cash_reserve_fraction)-gross))
    try: returns,dates=_aligned_returns(dataset,spec,as_of,lookback)
    except ValueError as exc:
        result.update(status="exposure_only",reason=str(exc));return result
    # Appreciated existing holdings can exceed their original envelope without
    # implying account leverage. Preserve dollars instead of rejecting/renormalizing
    # that overrun away. Covariance uses an explicit nonlevered computation basis.
    denominator=max(capital,gross)
    with localcontext() as context:
        context.prec=40
        weights={key:(value/denominator).quantize(D('1e-24'),rounding=ROUND_DOWN) for key,value in exposures.items()}
    estimate=portfolio_risk(returns,weights,dates,{i.instrument_id:i.risk_group for i in spec.universe})
    estimate.limitations[0]="Descriptive trailing sample estimate at the displayed quantity-derived weights; not a forecast guarantee or loss bound."
    dollars=D(str(estimate.annualized_volatility_fraction))*denominator
    result.update(status="estimated",reason="Aligned trailing covariance at the displayed quantities and decision prices",
        covariance=estimate.model_dump(mode="json"),annualized_volatility_usd=str(dollars),
        capital_relative_volatility_fraction=str(dollars/capital),covariance_denominator_usd=str(denominator))
    if gross>capital:
        result["limitations"].append("Holdings exceed their nominal envelope. Covariance weights use gross holdings value; dollar risk and envelope-relative risk preserve the full overrun. This alone does not establish account leverage.")
    return result
