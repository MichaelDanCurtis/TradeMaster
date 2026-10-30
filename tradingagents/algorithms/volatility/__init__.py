"""Volatility- and risk-aware execution algorithms.

These algorithms size or shape the entry as a function of risk inputs
(ATR, recent realized volatility, edge estimates, portfolio insurance
parameters) rather than as a function of price or volume profile.
"""

from tradingagents.algorithms.volatility import (
    atr_position_size,
    cppi,
    kelly_fraction,
    volatility_targeting,
)

__all__ = [
    "atr_position_size",
    "cppi",
    "kelly_fraction",
    "volatility_targeting",
]
