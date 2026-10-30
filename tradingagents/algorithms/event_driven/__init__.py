"""Event-driven execution algorithms.

These algorithms enter on a discrete signal: a news event with confirmed
volume, a post-earnings drift setup, or a sector-rotation cue. They are
the most "agent-coupled" of the algorithms — the upstream agent committee
supplies the trigger; the algorithm shapes the resulting order.
"""

from tradingagents.algorithms.event_driven import (
    earnings_drift,
    news_event_entry,
    sector_rotation,
)

__all__ = ["earnings_drift", "news_event_entry", "sector_rotation"]
