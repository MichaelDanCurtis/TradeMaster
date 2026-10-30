"""Momentum / trend-following execution algorithms.

These algorithms describe entries that trigger on confirmation of a trend
(breakout above a level, MA crossover, MACD signal, Donchian channel
break). Every plan pairs the entry with a paired stop on the opposite side
so the position has a defined risk-per-share from inception.
"""

from tradingagents.algorithms.momentum import (
    channel_breakout,
    donchian_turtle,
    dual_ma_crossover,
    macd_signal,
    momentum_breakout,
)

__all__ = [
    "channel_breakout",
    "donchian_turtle",
    "dual_ma_crossover",
    "macd_signal",
    "momentum_breakout",
]
