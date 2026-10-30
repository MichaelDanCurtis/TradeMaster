"""Synthetic fixtures for validating mechanics, never market evidence."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import math
from zoneinfo import ZoneInfo

from tradingagents.research.contracts import SnapshotManifest
from tradingagents.research.data.contracts import DatasetBundle
from tradingagents.research.data.store import ArtifactStore


def trend_fixture() -> DatasetBundle:
    zone = ZoneInfo("America/New_York")
    sessions, bars = [], []
    start = date(2018, 1, 1)
    # This is deliberately a weekday-only synthetic calendar, not an exchange
    # calendar. Metadata and evidence status retain that distinction.
    for offset in range(1100):
        day = start + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        index = len(sessions)
        opens = datetime.combine(day, time(9, 30), zone)
        closes = datetime.combine(day, time(16), zone)
        sessions.append({"date": day, "opens_at": opens, "closes_at": closes})
        for identifier, drift, phase in (("us-sim-eq", 0.015, 0), ("us-sim-bond", 0.005, 2)):
            opening = Decimal(str(round(100 + drift * index + 5 * math.sin(index / 31 + phase), 4)))
            closing = opening + Decimal(str(round(math.sin(index / 11 + phase) * .3, 4)))
            bars.append({"instrument_id": identifier, "session": day, "open": opening, "high": max(opening, closing) + 1, "low": min(opening, closing) - 1, "close": closing, "volume": 1000000, "available_at": closes + timedelta(seconds=1)})
    return DatasetBundle(timezone="America/New_York", sessions=sessions, bars=bars, mappings=[
        {"instrument_id": "us-sim-eq", "symbol": "SIM-EQ", "valid_from": start, "known_at": sessions[0]["opens_at"]},
        {"instrument_id": "us-sim-bond", "symbol": "SIM-BOND", "valid_from": start, "known_at": sessions[0]["opens_at"]},
    ])


def save_trend_fixture(store: ArtifactStore) -> SnapshotManifest:
    data = trend_fixture()
    return SnapshotManifest(
        provider="synthetic-trend-fixture-v1", evidence_kind="fixture",
        provenance="Deterministically generated prices for testing software; not real securities or returns.",
        entitlement="Locally generated test fixture", calendar="synthetic-weekdays-v1", timezone=data.timezone,
        coverage_start=data.sessions[0].date, coverage_end=data.sessions[-1].date,
        instrument_ids=["us-sim-eq", "us-sim-bond"], artifacts=store.put_dataset(data), availability="synthetic",
        limitations=["Synthetic weekday calendar includes market holidays", "Cannot support investment claims or paper promotion"],
    )
