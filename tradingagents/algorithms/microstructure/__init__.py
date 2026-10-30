"""Microstructure execution: bracket, trailing stop, ladder, adaptive limit, sniper.

These algorithms operate on the order book or the local price tape — they are
the lowest-level execution-style strategies. Three of them (`bracket_order`,
`trailing_stop`, `dca_ladder`) preserve exact behavior from the legacy
`ui.execution_algorithms` module so existing tests and API consumers continue
to work unchanged.
"""

from tradingagents.algorithms.microstructure import (
    adaptive_limit,
    bracket_order,
    dca_ladder,
    sniper,
    trailing_stop,
)

__all__ = [
    "adaptive_limit",
    "bracket_order",
    "dca_ladder",
    "sniper",
    "trailing_stop",
]
