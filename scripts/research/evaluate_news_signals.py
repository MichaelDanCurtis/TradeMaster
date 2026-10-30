"""Frozen exploratory news/forward-return association, not a trading backtest."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from scipy.stats import spearmanr

from scripts.research.build_news_signals import load_verified, sha, write_new
from tradingagents.research.news_signals import available_at, snapshot, timestamp


def correlation(rows, key="tone"):
    if len(rows) < 3 or len({r[key] for r in rows}) < 2 or len({r["excess_return"] for r in rows}) < 2:
        return None
    return float(spearmanr([r[key] for r in rows], [r["excess_return"] for r in rows]).statistic)


def evaluate(root):
    protocol = json.loads((root / "protocol.json").read_text())
    source, tones = load_verified(root / "history")
    panel_path = Path(protocol["price_source"])
    panel = json.loads(panel_path.read_text())
    dates = panel["dates"]
    prepared = json.loads((root / "diagnostic-lock.json").read_text())
    if sha(root / "protocol.json") != prepared["protocol_sha256"] or sha(panel_path) != prepared["panel_sha256"]:
        raise ValueError("Frozen protocol or price panel changed")
    expected = {"mode": "retrospective_proxy", "window_days": 7, "minimum_scored_headlines": 1,
                "model": "ProsusAI/finbert", "revision": "4556d13015211d73dccd3fdd39d39232506f3e43"}
    if any(protocol.get(k) != v for k, v in expected.items()):
        raise ValueError("Unsupported protocol configuration")
    if tones["model"] != protocol["model"] or tones["revision"] != protocol["revision"]:
        raise ValueError("Classifier differs from frozen protocol")
    for name, expected_hash in prepared["input_sha256"].items():
        if sha(root / name) != expected_hash:
            raise ValueError("Frozen news evidence changed")
    for filename, expected in prepared["code_sha256"].items():
        if sha(Path(filename)) != expected:
            raise ValueError("Diagnostic implementation changed after lock")
    calendar_path = Path(prepared["calendar_path"])
    if sha(calendar_path) != prepared["calendar_sha256"]:
        raise ValueError("Market calendar changed after lock")
    calendar = {r["date"]: r for r in json.loads(calendar_path.read_text())}
    requested = protocol["symbols"]
    groups = {s: sorted([a for a in source["articles"] if s in a["symbols"]],
                        key=lambda a: available_at(a, "retrospective_proxy")) for s in requested}
    times = {s: [available_at(a, "retrospective_proxy") for a in groups[s]] for s in requested}
    rows, exclusions, replays, weekly = [], [], [], []
    snapshots = []
    receipt = json.loads((root / "history/receipt.json").read_text())
    complete = receipt["complete"] and not source["quarantine"]
    for i, session in enumerate(dates):
        if session < protocol["scoring_start"] or session > protocol["scoring_end"] or i == 0:
            continue
        if date.fromisoformat(session).isocalendar()[:2] == date.fromisoformat(dates[i - 1]).isocalendar()[:2]:
            continue
        if i + 5 >= len(dates):
            continue
        previous_session = calendar[dates[i - 1]]
        cutoff = datetime.fromisoformat(previous_session["date"] + "T" + previous_session["close"]).replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
        start = cutoff - timedelta(days=7)
        in_bounds = timestamp(receipt["query"]["start"]) <= start and cutoff <= timestamp(receipt["query"]["end"])
        period = []
        for symbol in requested:
            subset = groups[symbol][bisect_left(times[symbol], start):bisect_left(times[symbol], cutoff)]
            snap = snapshot(subset, tones["records"], symbol, cutoff.isoformat(),
                            mode="retrospective_proxy", coverage_complete=complete and in_bounds)
            snapshots.append(snap)
            value = snap["mean_headline_tone"]
            if value is None:
                exclusions.append({"symbol": symbol, "entry": session, "reason": "no_single_ticker_tone"})
                continue
            prices = [panel["series"][s]["open"][j] for s in [symbol, "SPY"] for j in [i, i + 5]]
            if any(p is None or not np.isfinite(p) or p <= 0 for p in prices):
                exclusions.append({"symbol": symbol, "entry": session, "reason": "missing_price"})
                continue
            stock_return, benchmark_return = prices[1] / prices[0] - 1, prices[3] / prices[2] - 1
            row = {"symbol": symbol, "cutoff": cutoff.isoformat(), "entry": session, "exit": dates[i + 5],
                   "tone": value, "scored_count": snap["scored_single_ticker_count"],
                   "stock_return": stock_return, "spy_return": benchmark_return,
                   "excess_return": stock_return - benchmark_return}
            rows.append(row)
            period.append(row)
        weekly.append({"entry": session, "observations": len(period), "spearman_ic": correlation(period)})
    # Replaying the full archive vs past-only rows must yield identical features.
    # Both retain identical tone results; retrospective inference remains labeled.
    for index in range(len(snapshots)):
        example = snapshots[index]
        cutoff = timestamp(example["cutoff"])
        stock = example["symbol"]
        full = snapshot(groups[stock], tones["records"], stock, example["cutoff"],
                        mode="retrospective_proxy", coverage_complete=example["coverage"] == "endpoint_complete")
        past = [a for a in groups[stock] if available_at(a, "retrospective_proxy") < cutoff]
        replay = snapshot(past, tones["records"], stock, example["cutoff"],
                          mode="retrospective_proxy", coverage_complete=example["coverage"] == "endpoint_complete")
        if full != replay or full != example:
            raise ValueError("Causal replay mismatch")
        replays.append({"symbol": stock, "cutoff": example["cutoff"], "passed": True})
    year_rows = []
    for year in ["2024", "2025"]:
        subset = [r for r in rows if r["entry"].startswith(year)]
        weekly_ics = [r["spearman_ic"] for r in weekly if r["entry"].startswith(year) and r["spearman_ic"] is not None]
        year_rows.append({"year": year, "observations": len(subset), "pooled_spearman": correlation(subset),
                          "mean_weekly_spearman": float(np.mean(weekly_ics)) if weekly_ics else None})
    result = {"protocol_sha256": sha(root / "protocol.json"), "lock_sha256": sha(root / "diagnostic-lock.json"),
              "articles_sha256": sha(root / "history/articles.json"), "tones_sha256": sha(root / "history/tones.json"),
              "rows": rows, "weekly": weekly, "by_year": year_rows, "excluded": exclusions,
              "causal_replays": replays, "snapshot_count": len(snapshots),
              "pooled_spearman": correlation(rows), "no_trading_backtest": True,
              "qualification": "Selected current tickers, headline-only single-source archive proxy. Correlations are descriptive, overlapping and not risk/cost-adjusted alpha evidence."}
    write_new(root / "diagnostic.json", result)
    write_new(root / "historical-snapshots.json", snapshots)
    print(json.dumps({"snapshot_count": len(snapshots), "observations": len(rows),
                      "by_year": year_rows, "excluded": dict(Counter(r["reason"] for r in exclusions))}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    evaluate(parser.parse_args().root)
