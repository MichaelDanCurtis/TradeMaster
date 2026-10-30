from datetime import date, timedelta
from decimal import Decimal as D
from math import sqrt

import pytest

from tradingagents.research.strategies.portfolio_risk import portfolio_risk


def estimate(a, b, weights=(".5", ".5")):
    return portfolio_risk({"A":list(map(D,a)),"B":list(map(D,b))},
        dict(zip(("A","B"),map(D,weights))),
        [date(2026,1,1)+timedelta(days=i) for i in range(len(a))],
        {"A":"equity","B":"rates"})


def test_equal_individual_volatility_does_not_imply_equal_portfolio_risk():
    # Each asset has 1% sample daily volatility. Perfect positive correlation
    # gives 1% portfolio volatility; exact negative correlation hedges it away.
    same=estimate(["-.01","0",".01"],["-.01","0",".01"])
    assert same.annualized_volatility_fraction == pytest.approx(.01*sqrt(252))
    assert same.annualized_volatility_assuming_independence_fraction == pytest.approx(.01*sqrt(126))
    assert same.diversification_ratio == pytest.approx(1)
    assert same.group_variance_shares == {"equity":.5,"rates":.5}
    opposite=estimate(["-.01","0",".01"],[".01","0","-.01"])
    assert opposite.annualized_volatility_fraction == 0
    assert opposite.diversification_ratio is None
    assert all(c.share_of_portfolio_variance is None for c in opposite.contributions.values())


def test_covariance_contributions_include_negative_hedging_and_sum_to_risk():
    risk=estimate(["-.01","0",".01"],[".01","0","-.01"],(".6",".2"))
    assert risk.annualized_volatility_fraction == pytest.approx(.004*sqrt(252))
    assert risk.contributions["A"].share_of_portfolio_variance == pytest.approx(1.5)
    assert risk.contributions["B"].share_of_portfolio_variance == pytest.approx(-.5)
    assert sum(c.annualized_volatility_contribution_fraction for c in risk.contributions.values()) == pytest.approx(risk.annualized_volatility_fraction)
    # Uninvested cash remains 20%, without normalizing the weights upward.
    assert risk.invested_fraction == D(".8")


def test_uncorrelated_series_agree_with_independence_diagnostic():
    # Centered dot product is zero, including the sample-mean adjustment.
    risk=estimate(["-.01","0",".01"],[".01","-.02",".01"])
    assert risk.annualized_volatility_fraction == pytest.approx(.01*sqrt(252))
    assert risk.annualized_volatility_assuming_independence_fraction == pytest.approx(risk.annualized_volatility_fraction)
    assert risk.contributions["A"].share_of_portfolio_variance == pytest.approx(.25)


def test_cash_only_and_constant_prices_have_zero_observed_variance_not_invented_risk():
    cash=estimate(["-.01","0",".01"],[".01","0","-.01"],("0","0"))
    assert cash.annualized_volatility_fraction == 0 and cash.invested_fraction == 0
    constant=estimate([".02"]*3,[".01"]*3)
    assert constant.annualized_volatility_fraction == 0
    assert constant.diversification_ratio is None
    assert any("not proof" in note for note in constant.limitations)


@pytest.mark.parametrize("a,b,weights", [
    (["0"],["0"],(".5",".5")),
    (["0",".01"],["0"],(".5",".5")),
    (["0","NaN"],["0","0"],(".5",".5")),
    (["0","-1.01"],["0","0"],(".5",".5")),
    (["0",".01"],["0","0"],(".8",".8")),
])
def test_invalid_samples_or_leverage_are_not_silently_repaired(a,b,weights):
    with pytest.raises(ValueError): estimate(a,b,weights)
