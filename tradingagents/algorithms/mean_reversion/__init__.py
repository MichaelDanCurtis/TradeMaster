"""Mean-reversion execution algorithms.

These algorithms enter against a stretched move on the assumption it will
revert toward a reference (mean, midline, VWAP, pair spread). Each plan
pairs the entry with a take-profit at the reversion target and a stop
beyond the extreme — defining both the upside and the invalidation level.
"""

from tradingagents.algorithms.mean_reversion import (
    bollinger_band,
    pair_spread,
    rsi_extremes,
    vwap_reversion,
    zscore_reversion,
)

__all__ = [
    "bollinger_band",
    "pair_spread",
    "rsi_extremes",
    "vwap_reversion",
    "zscore_reversion",
]
