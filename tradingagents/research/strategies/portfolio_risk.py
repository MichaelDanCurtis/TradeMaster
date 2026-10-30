"""Descriptive covariance risk of fixed proposed weights, without optimization.

Sample variance of the aligned weighted return series equals w' Sigma w.
Computing Sigma w directly avoids storing a quadratic matrix in every decision.
All observations use the same sessions; no pairwise deletion or imputation.
"""
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import Field

from tradingagents.research.contracts import Contract, Digest, Fraction, content_hash


class RiskContribution(Contract):
    weight: Fraction
    annualized_standalone_volatility_fraction: float
    annualized_covariance_with_portfolio: float
    annualized_volatility_contribution_fraction: float | None
    share_of_portfolio_variance: float | None


class PortfolioRiskEstimate(Contract):
    method: Literal["aligned_sample_covariance_v1"] = "aligned_sample_covariance_v1"
    observations: int = Field(ge=2)
    first_return_session: date
    last_return_session: date
    annualization_sessions: Literal[252] = 252
    input_hash: Digest
    invested_fraction: Fraction
    annualized_volatility_fraction: float
    annualized_volatility_assuming_independence_fraction: float
    diversification_ratio: float | None
    contributions: dict[str, RiskContribution]
    group_variance_shares: dict[str, float | None]
    limitations: list[str]


def portfolio_risk(returns: dict[str, list[Decimal]], weights: dict[str, Decimal],
                   sessions: list[date], groups: dict[str, str]) -> PortfolioRiskEstimate:
    if len(sessions) < 2 or sessions != sorted(set(sessions)):
        raise ValueError("Covariance needs at least two unique, ordered return sessions")
    if not returns or set(returns) != set(weights) or set(groups) != set(weights):
        raise ValueError("Covariance inputs must identify the same instruments")
    if any(len(series) != len(sessions) for series in returns.values()):
        raise ValueError("Covariance requires complete aligned observations")
    if any(not value.is_finite() or value < -1 for series in returns.values() for value in series):
        raise ValueError("Total returns must be finite and cannot lose more than their capital")
    if any(not w.is_finite() or w < 0 or w > 1 for w in weights.values()) or sum(weights.values()) > 1:
        raise ValueError("Risk weights must be unlevered capital fractions")
    with localcontext() as context:
        context.prec = 40
        n, annual = Decimal(len(sessions)), Decimal(252)
        ids = sorted(returns)
        means = {key:sum(returns[key])/n for key in ids}
        centered = {key:[value-means[key] for value in returns[key]] for key in ids}
        portfolio = [sum((weights[key]*centered[key][index] for key in ids), Decimal(0)) for index in range(len(sessions))]
        variance = annual*sum((value*value for value in portfolio), Decimal(0))/(n-1)
        volatility = variance.sqrt()
        contributions, group_values = {}, {}
        independent_variance = standalone_sum = Decimal(0)
        for key in ids:
            asset_variance = annual*sum((value*value for value in centered[key]), Decimal(0))/(n-1)
            covariance = annual*sum((a*b for a,b in zip(centered[key], portfolio)), Decimal(0))/(n-1)
            variance_contribution = weights[key]*covariance
            independent_variance += weights[key]**2*asset_variance
            standalone_sum += weights[key]*asset_variance.sqrt()
            group_values[groups[key]] = group_values.get(groups[key], Decimal(0))+variance_contribution
            contributions[key] = RiskContribution(weight=weights[key],
                annualized_standalone_volatility_fraction=float(asset_variance.sqrt()),
                annualized_covariance_with_portfolio=float(covariance),
                annualized_volatility_contribution_fraction=float(variance_contribution/volatility) if volatility else None,
                share_of_portfolio_variance=float(variance_contribution/variance) if variance else None)
        limitations = [
            "Descriptive trailing sample estimate at proposed weights, before share rounding and fills; not a volatility target, forecast guarantee or loss bound.",
            "Cash is treated as constant-value USD for this price-risk estimate. Changing cash yields, execution costs, gaps and liquidity risk are not modeled here.",
            "All assets use the same completed return sessions and explicit available corporate actions. No volatility floor, shrinkage or independence assumption is applied to portfolio covariance.",
            "Annualization uses 252 sessions and does not estimate serial dependence. Correlations can change outside this sample.",
        ]
        if len(sessions) < 20:
            limitations.append("Fewer than 20 return observations: this short-window diagnostic is especially unstable.")
        if len(sessions) <= sum(weight > 0 for weight in weights.values()):
            limitations.append("The sample covariance is necessarily rank deficient for the invested universe; no matrix inversion or optimization is performed.")
        if not volatility:
            limitations.append("Observed portfolio variance is zero; normalized risk contributions and diversification ratio are undefined, not proof of a risk-free portfolio.")
        return PortfolioRiskEstimate(observations=len(sessions), first_return_session=sessions[0], last_return_session=sessions[-1],
            input_hash=content_hash({"returns":{key:[format(value.normalize(),"f") for value in values] for key,values in returns.items()},
                "weights":{key:format(value.normalize(),"f") for key,value in weights.items()},
                "sessions":[day.isoformat() for day in sessions],"groups":groups}),
            invested_fraction=sum(weights.values()), annualized_volatility_fraction=float(volatility),
            annualized_volatility_assuming_independence_fraction=float(independent_variance.sqrt()),
            diversification_ratio=float(standalone_sum/volatility) if volatility else None,
            contributions=contributions,
            group_variance_shares={group:float(value/variance) if variance else None for group,value in group_values.items()},
            limitations=limitations)
