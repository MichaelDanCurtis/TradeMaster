from datetime import datetime, timedelta
from decimal import Decimal

from tradingagents.research.contracts import StrategySpec
from tradingagents.research.data.fixtures import trend_fixture
from tradingagents.research.strategies.trend import cap_weights, trend_targets
from tests.research.conftest import spec_payload


def fixture_spec():
    payload = spec_payload()
    payload["universe"] = [{"instrument_id": "us-sim-eq", "symbol": "SIM-EQ", "risk_group": "equity"}, {"instrument_id": "us-sim-bond", "symbol": "SIM-BOND", "risk_group": "rates"}]
    return StrategySpec.model_validate(payload)


def test_missing_or_unavailable_bar_does_not_become_an_exit_signal():
    dataset = trend_fixture()
    spec = fixture_spec()
    session = dataset.sessions[10]
    assert trend_targets(dataset, spec, session.closes_at).status == "no_signal"
    decision = trend_targets(dataset, spec, session.closes_at + timedelta(seconds=2))
    assert decision.status == "targets"
    dataset.bars = [bar for bar in dataset.bars if not (bar.instrument_id == "us-sim-eq" and bar.session == session.date)]
    missing = trend_targets(dataset, spec, session.closes_at + timedelta(seconds=2))
    assert missing.status == "no_signal" and missing.weights == {}


def test_future_prices_cannot_change_past_targets():
    dataset = trend_fixture()
    spec = fixture_spec()
    session = dataset.sessions[10]
    as_of = session.closes_at + timedelta(seconds=2)
    before = trend_targets(dataset, spec, as_of)
    for bar in dataset.bars:
        if bar.session > session.date:
            bar.close *= 10
    assert trend_targets(dataset, spec, as_of) == before


def test_caps_preserve_unused_cash_without_reinflation():
    spec = fixture_spec()
    spec.risk.max_position_fraction = Decimal("0.2")
    spec.risk.max_group_fraction = Decimal("0.3")
    spec.universe[1].risk_group = "equity"
    weights = cap_weights({"us-sim-eq": Decimal(1), "us-sim-bond": Decimal(1)}, spec)
    assert weights == {"us-sim-eq": Decimal("0.15"), "us-sim-bond": Decimal("0.15")}
    assert sum(weights.values()) == Decimal("0.3")


def test_split_and_dividend_leave_total_return_signal_economically_unchanged():
    dataset = trend_fixture()
    spec = fixture_spec()
    session = dataset.sessions[10]
    as_of = session.closes_at + timedelta(seconds=2)
    original = trend_targets(dataset, spec, as_of)
    from tradingagents.research.data.contracts import CorporateAction
    effective = dataset.sessions[8]
    dataset.actions.append(CorporateAction(action_id="split", instrument_id="us-sim-eq", kind="split", effective_session=effective.date, available_at=effective.opens_at, split_ratio="2"))
    for bar in dataset.bars:
        if bar.instrument_id == "us-sim-eq" and bar.session >= effective.date:
            bar.open /= 2; bar.high /= 2; bar.low /= 2; bar.close /= 2
    split = trend_targets(dataset, spec, as_of)
    assert split.signals == original.signals
    assert split.annualized_volatility == original.annualized_volatility
    assert split.portfolio_risk == original.portfolio_risk
    # Ex-dividend drop offsets explicit cash in the same session's return.
    last = next(bar for bar in dataset.bars if bar.instrument_id == "us-sim-eq" and bar.session == session.date)
    last.close -= Decimal("1")
    dataset.actions.append(CorporateAction(action_id="dividend", instrument_id="us-sim-eq", kind="dividend", effective_session=session.date, available_at=session.opens_at, cash_per_share_usd="1"))
    dividend = trend_targets(dataset, spec, as_of)
    assert dividend.signals == original.signals
    assert dividend.annualized_volatility == original.annualized_volatility
    assert dividend.portfolio_risk == original.portfolio_risk


def test_covariance_uses_the_declared_available_return_window_and_exact_capped_weights():
    dataset, spec = trend_fixture(), fixture_spec()
    as_of=dataset.sessions[10].closes_at+timedelta(seconds=2)
    result=trend_targets(dataset,spec,as_of)
    risk=result.portfolio_risk
    assert risk.observations == spec.rules.volatility_sessions
    assert risk.first_return_session == dataset.sessions[11-spec.rules.volatility_sessions].date
    assert risk.last_return_session == dataset.sessions[10].date
    assert {key:value.weight for key,value in risk.contributions.items()} == result.weights
    assert risk.invested_fraction == sum(result.weights.values())
    # A missing available bar prevents targets and a covariance claim alike.
    dataset.bars=[bar for bar in dataset.bars if bar.session!=dataset.sessions[10].date]
    unavailable=trend_targets(dataset,spec,as_of)
    assert unavailable.portfolio_risk is None and unavailable.status=="no_signal"
