"""Time-based execution: TWAP, VWAP, POV, Iceberg, Implementation Shortfall.

These algorithms schedule child orders across a time window. They differ in
HOW the schedule is shaped (equal? volume-weighted? front-loaded?) and WHAT
the broker reveals to the market (full? hidden? participation-capped?).
"""

from tradingagents.algorithms.time_based import (
    iceberg,
    implementation_shortfall,
    pov,
    twap,
    vwap,
)

__all__ = ["iceberg", "implementation_shortfall", "pov", "twap", "vwap"]
