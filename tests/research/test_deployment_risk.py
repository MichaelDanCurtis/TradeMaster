"""Hand-calculated dollar risk of quantities; synthetic engineering only."""
from datetime import timedelta
from decimal import Decimal as D
from math import sqrt

import pytest

from tests.research.test_trend import fixture_spec
from tests.research.test_deployment import desk
from tests.research.test_deployment_evaluation import evaluated
from tradingagents.research.data.fixtures import trend_fixture
from tradingagents.research.strategies.deployment_risk import funded_portfolio_risk


def sample():
    data=trend_fixture();spec=fixture_spec()
    spec.rules.lookbacks_sessions=[2,3];spec.rules.volatility_sessions=3
    data.sessions=data.sessions[:4]
    days=[s.date for s in data.sessions]
    prices={"us-sim-eq":["100","99","99","99.99"],"us-sim-bond":["100","101","101","99.99"]}
    data.bars=[b.model_copy(update={key:D(prices[b.instrument_id][days.index(b.session)]) for key in ("open","high","low","close")}) for b in data.bars if b.session in days]
    return data,spec,data.sessions[-1].closes_at+timedelta(seconds=1)


def risk(data,spec,at,quantities=None,capital="1000"):
    return funded_portfolio_risk(data,spec,at,D(capital),quantities or {"us-sim-eq":D(2),"us-sim-bond":D(1)},basis="proposed_whole_shares")


def test_known_quantities_produce_independently_calculated_dollar_covariance():
    data,spec,at=sample();result=risk(data,spec,at)
    assert result["status"]=="estimated"
    assert D(result["gross_exposure_usd"])==D("299.97")
    assert D(result["unused_envelope_usd"])==D("700.03")
    assert float(result["annualized_volatility_usd"])==pytest.approx(.9999*sqrt(252))
    assert float(result["capital_relative_volatility_fraction"])==pytest.approx(.0009999*sqrt(252))
    contributions=result["covariance"]["contributions"]
    assert contributions["us-sim-eq"]["share_of_portfolio_variance"]==pytest.approx(2)
    assert contributions["us-sim-bond"]["share_of_portfolio_variance"]==pytest.approx(-1)
    assert result["covariance"]["observations"]==3
    assert all(not row["over_limit"] for row in result["positions"]+result["groups"])


def test_holdings_over_nominal_funding_preserve_dollar_risk_and_limit_breaches():
    data,spec,at=sample()
    result=risk(data,spec,at,{"us-sim-eq":D(20),"us-sim-bond":D(10)})
    assert D(result["gross_exposure_usd"])==D("2999.70")
    assert D(result["unused_envelope_usd"])==D("-1999.70")
    assert D(result["covariance_denominator_usd"])==D("2999.70")
    assert float(result["annualized_volatility_usd"])==pytest.approx(9.999*sqrt(252))
    assert all(row["over_limit"] for row in result["positions"]+result["groups"])
    assert any("does not establish account leverage" in note for note in result["limitations"])


def test_missing_or_late_history_keeps_exposure_but_does_not_invent_covariance():
    data,spec,at=sample()
    data.bars=[b for b in data.bars if not(b.instrument_id=="us-sim-eq" and b.session==data.sessions[1].date)]
    result=risk(data,spec,at)
    assert result["status"]=="exposure_only" and result["covariance"] is None
    assert D(result["gross_exposure_usd"])==D("299.97")
    data.bars=[b.model_copy(update={"available_at":at+timedelta(seconds=1)}) if b.session==data.sessions[-1].date else b for b in data.bars]
    result=risk(data,spec,at)
    assert result["status"]=="unavailable" and result["gross_exposure_usd"] is None


def test_zero_quantity_is_zero_observed_risk_with_undefined_normalized_contributions():
    data,spec,at=sample()
    result=risk(data,spec,at,{"us-sim-eq":D(0),"us-sim-bond":D(0)})
    assert result["status"]=="estimated" and D(result["annualized_volatility_usd"])==0
    assert all(c["share_of_portfolio_variance"] is None for c in result["covariance"]["contributions"].values())


def test_future_prices_cannot_change_decision_risk():
    data,spec,at=sample();before=risk(data,spec,at)
    data.bars += [b.model_copy(update={"session":b.session+timedelta(days=30),"available_at":at+timedelta(days=30),"close":D(999999)}) for b in data.bars]
    assert risk(data,spec,at)==before


def test_split_and_dividend_remove_mechanical_price_moves_only_when_available():
    from tradingagents.research.data.contracts import CorporateAction
    data,spec,at=sample();days=[s.date for s in data.sessions]
    prices={"us-sim-eq":["100","50","49","49"],"us-sim-bond":["100"]*4}
    data.bars=[b.model_copy(update={key:D(prices[b.instrument_id][days.index(b.session)]) for key in ("open","high","low","close")}) for b in data.bars]
    data.actions=[CorporateAction(action_id="risk-split",instrument_id="us-sim-eq",kind="split",effective_session=days[1],available_at=at+timedelta(seconds=1),split_ratio=2),
        CorporateAction(action_id="risk-dividend",instrument_id="us-sim-eq",kind="dividend",effective_session=days[2],available_at=data.sessions[2].opens_at,cash_per_share_usd=1)]
    assert D(risk(data,spec,at)["annualized_volatility_usd"])>0
    data.actions[0].available_at=data.sessions[1].opens_at
    result=risk(data,spec,at)
    assert D(result["annualized_volatility_usd"])==0
    assert D(result["gross_exposure_usd"])==D(198)


def test_evaluation_persists_rounded_and_observed_risk_separately(desk,monkeypatch):
    active,evaluator,evaluation,request=evaluated(desk,monkeypatch)
    saved=evaluator.detail(active.deployment_id)["evaluations"][0].payload
    proposed=saved["funded_risk"]["proposed"];observed=saved["funded_risk"]["observed"]
    assert proposed["status"]=="estimated" and observed["status"]=="estimated"
    assert D(observed["gross_exposure_usd"])==0
    assert D(proposed["gross_exposure_usd"])==sum(D(r["desired_quantity"])*D(r["reference_price_usd"]) for r in saved["portfolio"])
    assert D(proposed["covariance"]["invested_fraction"])<D(saved["decision"]["portfolio_risk"]["invested_fraction"])
    receipt,_=desk[2]()
    assert evaluator.evaluate(active.deployment_id,request,receipt.reconciliation_id,desk[6][1]).payload["funded_risk"]==saved["funded_risk"]
