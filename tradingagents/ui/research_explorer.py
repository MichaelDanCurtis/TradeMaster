"""Read-only research leads from provider observations, without model ratings."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ExplorerSource(BaseModel):
    source: str
    status: str
    observed_at: str
    provider_updated_at: str | None = None
    message: str = ""


class ExplorerCandidate(BaseModel):
    symbol: str
    price: float | None = None
    change_pct: float | None = None
    volume: int | None = None
    sources: list[str] = Field(default_factory=list)


class ExplorerResponse(BaseModel):
    observed_at: str
    provider: str = "Alpaca stock screener"
    sources: list[ExplorerSource]
    candidates: list[ExplorerCandidate]


def finite_number(value: Any, *, positive: bool = False) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and (not positive or number > 0) else None


def explore_market(provider: Any) -> ExplorerResponse:
    """Bounded reads, partial failure reporting, and interleaved provider rankings.

    No cache: observation times belong to this request. Source update times are
    retained separately; a successful weekend read is not a live market quote.
    """
    sources: list[ExplorerSource] = []
    payloads: dict[str, dict] = {}
    for name, method, kwargs in (
        ("movers", "stock_movers", {"top": 25}),
        ("activity", "most_active_stocks", {"by": "volume", "top": 25}),
    ):
        observed = datetime.now(timezone.utc).isoformat()
        try:
            payload = getattr(provider, method)(**kwargs)
            keys = ("gainers", "losers") if name == "movers" else ("most_actives",)
            if not isinstance(payload, dict) or any(not isinstance(payload.get(key), list) for key in keys):
                raise ValueError("Unexpected screener response")
            payloads[name] = payload
            sources.append(ExplorerSource(
                source=name, status="available", observed_at=observed,
                provider_updated_at=str(payload["last_updated"]) if payload.get("last_updated") else None,
            ))
        except Exception:  # Provider errors must not leak credentials or hide the other source.
            sources.append(ExplorerSource(source=name, status="unavailable", observed_at=observed,
                message="Could not read this source. Check the Alpaca market-data connection in Settings, then retry."))

    buckets = [
        ("gainer", payloads.get("movers", {}).get("gainers", [])),
        ("loser", payloads.get("movers", {}).get("losers", [])),
        ("most_active", payloads.get("activity", {}).get("most_actives", [])),
    ]
    candidates: dict[str, ExplorerCandidate] = {}
    # Round-robin preserves each provider list's order without burying declines
    # and activity beneath 25 gainers. This is a browse order, not a return score.
    for index in range(25):
        for source, rows in buckets:
            if index >= len(rows) or not isinstance(rows[index], dict):
                continue
            row = rows[index]
            symbol = str(row.get("symbol") or "").strip().upper()
            if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", symbol):
                continue
            candidate = candidates.setdefault(symbol, ExplorerCandidate(symbol=symbol))
            if source not in candidate.sources:
                candidate.sources.append(source)
            if source != "most_active":
                candidate.price = finite_number(row.get("price"), positive=True)
                candidate.change_pct = finite_number(row.get("percent_change"))
            else:
                volume = finite_number(row.get("volume"), positive=True)
                candidate.volume = int(volume) if volume is not None else None
    return ExplorerResponse(observed_at=datetime.now(timezone.utc).isoformat(),
                            sources=sources, candidates=list(candidates.values()))
