"""Rebuild saved wide panels from hashed raw responses, independently of capture code."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np

FIELD_PAIRS = [("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v"), ("vwap", "vw")]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def verify(root):
    universe = read(root/"universe.json")
    original = root/"universe-source"/"universe-initial.json"
    assert sha(original) == universe["source_sha256"]
    initial = read(original); final = read(root/"universe-source"/"universe.json")
    assert initial["current_members"] == final["current_members"]
    members = initial["current_members"]
    assert sorted(r["symbol"] for r in members) == universe["sp500_symbols"]
    assert {r["symbol"]:r["sector"] for r in members} == universe["sectors"]
    assert {r["symbol"]:r["cik"] for r in members} == universe["issuers"]
    assert {r["symbol"]:r["security"] for r in members} == universe["names"]
    # Recreate deterministic diversity selection without reading price availability.
    key = lambda s: hashlib.sha256(("prediction-wide-v1:"+s).encode()).hexdigest()
    sectors = sorted(set(universe["sectors"].values()))
    extra = min(sectors, key=key)
    selected = []; issuers = set()
    for sector in sectors:
        count = 0
        for symbol in sorted([s for s in universe["sp500_symbols"] if universe["sectors"][s] == sector], key=key):
            cik = universe["issuers"][symbol]
            if cik in issuers: continue
            selected.append(symbol); issuers.add(cik); count += 1
            if count == 9 + int(sector == extra): break
    assert sorted(selected) == universe["diverse100_symbols"] and len(selected) == 100
    assert extra == universe["extra_sector"]
    assert Counter(universe["sectors"][s] for s in selected) == universe["diverse100_sector_counts"]

    receipt = read(root/"capture"/"receipt.json")
    assert receipt["complete"] is True
    source_receipt = root/"capture"/"source-receipt.json"
    assert receipt["source_receipt_sha256"] == sha(source_receipt)
    assert read(source_receipt) == {k:receipt[k] for k in ("universe_sha256", "intent_sha256", "responses")}
    assert receipt["universe_sha256"] == sha(root/"universe.json")
    assert receipt["intent_sha256"] == sha(root/"intent.json")
    assert datetime.fromisoformat(universe["frozen_at"]) < min(datetime.fromisoformat(r["observed_at"]) for r in receipt["responses"].values())
    assert all(sha(root/"capture"/"raw"/name) == value["sha256"] for name, value in receipt["responses"].items())
    names = universe["sp500_symbols"] + ["SPY"]
    calendar = read(root/"capture"/"raw"/"calendar.json")
    dates = sorted(r["date"] for r in calendar)
    assert len(dates) == len(set(dates)) and dates[-1] == "2026-09-04"
    day_index = {d:i for i,d in enumerate(dates)}; symbol_index = {s:i for i,s in enumerate(names)}
    rebuilt = np.full((len(names), len(dates), 6), np.nan)
    raw_days = {s:set() for s in names}; zero_volume = {s:[] for s in names}
    anomalies = []; zero_vwap_count = 0; raw_bar_count = 0; off_calendar = []
    groups = {}
    for name in receipt["responses"]:
        if name.startswith("bars-"):
            _, chunk, page = name[:-5].split("-")
            groups.setdefault(int(chunk), {})[int(page)] = name
    assert sorted(groups) == list(range((len(names)+79)//80))
    for chunk, pages in sorted(groups.items()):
        assert sorted(pages) == list(range(len(pages)))
        expected_names = names[80*chunk:80*(chunk+1)]
        previous_token = None
        for page, filename in sorted(pages.items()):
            meta = receipt["responses"][filename]; params = meta["params"]
            expected = {"symbols": ",".join(expected_names), "start": "2016-01-01", "end": "2026-09-04T23:59:59Z", "timeframe": "1Day",
                        "limit": 10000, "sort": "asc", "adjustment": "all", "asof": "2026-09-04", "feed": "sip", "currency": "USD"}
            if page: expected["page_token"] = previous_token
            assert params == expected
            payload = read(root/"capture"/"raw"/filename)
            for symbol, bars in payload["bars"].items():
                assert symbol in expected_names
                for bar in bars:
                    day = datetime.fromisoformat(bar["t"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).date().isoformat()
                    assert day not in raw_days[symbol]
                    raw_days[symbol].add(day); raw_bar_count += 1
                    values = np.array([float(bar[key]) for _, key in FIELD_PAIRS])
                    assert np.isfinite(values).all() and (values[:4] > 0).all() and (values[4:] >= 0).all()
                    if values[2] > min(values[0],values[3])+1e-5 or values[1] < max(values[0],values[3])-1e-5:
                        anomalies.append({"symbol": symbol, "date": day, "kind": "inconsistent_ohlc"})
                    if values[5] == 0:
                        values[5] = np.nan; zero_vwap_count += 1
                    if values[4] == 0:
                        values[0] = np.nan; zero_volume[symbol].append(day)
                        anomalies.append({"symbol": symbol, "date": day, "kind": "zero_volume_open_not_executable"})
                    if day in day_index: rebuilt[symbol_index[symbol], day_index[day]] = values
                    else: off_calendar.append({"symbol": symbol, "date": day})
            previous_token = payload.get("next_page_token")
            if page < max(pages): assert previous_token
            else: assert previous_token is None
    coverage = read(root/"capture"/"coverage.json")
    assert coverage["sessions"] == len(dates) and coverage["symbols"] == len(names) and coverage["bars"] == raw_bar_count
    assert coverage["anomalies"] == anomalies
    for symbol in names:
        available = sorted(raw_days[symbol] & set(dates))
        expected = {"bars":len(available), "first": available[0] if available else None, "last": available[-1] if available else None,
                    "interior_missing": [d for d in dates if available and available[0] <= d <= available[-1] and d not in raw_days[symbol]],
                    "total_missing": len(dates)-len(available), "zero_volume": sorted(d for d in zero_volume[symbol] if d in day_index)}
        assert expected == coverage["per_symbol"][symbol], symbol
    panel_checks = []
    for filename, symbols in [("panel-sp500.json", universe["sp500_symbols"]), ("panel-diverse100.json", universe["diverse100_symbols"])]:
        path = root/filename; panel = read(path)
        assert sha(path) == receipt["panel_sha256"][filename]
        assert panel["dates"] == dates and panel["symbols"] == symbols and panel["benchmark"] == "SPY"
        assert set(panel["series"]) == set(symbols+["SPY"])
        assert panel["sectors"] == {s:universe["sectors"][s] for s in symbols}
        assert panel["issuers"] == {s:universe["issuers"][s] for s in symbols}
        assert panel["membership"] is None
        assert panel["capture_source_sha256"] == sha(source_receipt)
        checked = 0; nulls = 0
        for symbol in symbols+["SPY"]:
            for field_index,(field,_) in enumerate(FIELD_PAIRS):
                actual = np.array(panel["series"][symbol][field], dtype=float)
                expected = rebuilt[symbol_index[symbol], :, field_index]
                assert np.array_equal(actual, expected, equal_nan=True), (symbol, field)
                checked += len(expected); nulls += int(np.isnan(actual).sum())
        panel_checks.append({"file": filename, "symbols": len(symbols), "cells_checked":checked, "null_cells":nulls, "exact_match":True})
    # Flag, never repair, large adjusted-close discontinuities and provider continuity.
    jumps = []
    for symbol in names:
        close = rebuilt[symbol_index[symbol], :, 3]
        for i in range(1,len(dates)):
            if np.isfinite(close[i-1:i+1]).all():
                change = close[i]/close[i-1]-1
                if abs(change) >= .5:
                    jumps.append({"symbol":symbol,"date":dates[i],"prior_date":dates[i-1],"prior_close":float(close[i-1]),"close":float(close[i]),"simple_return":float(change)})
    identities = []
    for symbol in ["EXE","SNDK","FDXF","HONA","GEV","GEHC","VMRK","MRSH","BNY","ECHO","META","BALL","ELV","WTW"]:
        c = coverage["per_symbol"].get(symbol)
        if c: identities.append({"symbol":symbol,**c})
    return {"state":"passed_with_source_limitations", "checked_at":datetime.now(timezone.utc).isoformat(),
            "method":"Independent response-page replay and full numeric/null panel reconstruction; seeded sector selection reconstructed without prices",
            "source_linkage":{"frozen_universe_sha256":sha(root/"universe.json"),"initial_source_sha256":sha(original),
                              "final_source_sha256":sha(root/"universe-source"/"universe.json"),"all_selection_metadata_unchanged":True,
                              "note":"Recovered intermediate source JSON is byte-identical to the frozen reference; later changes only add source checks/provenance. Original path was overwritten; matching version retained as universe-initial.json.",
                              "github_revision":initial["github_revision"],"frozen_source_revision_field_was_null":universe["source_revision"] is None},
            "responses_verified":len(receipt["responses"]),"raw_bars_verified":raw_bar_count,"sessions":len(dates),
            "requested_stock_count":len(universe["sp500_symbols"]),
            "stocks_with_any_bars":sum(coverage["per_symbol"][s]["bars"]>0 for s in universe["sp500_symbols"]),
            "stocks_with_no_bars":[s for s in universe["sp500_symbols"] if coverage["per_symbol"][s]["bars"]==0],
            "panel_checks":panel_checks,"normalization":{"zero_vwap_to_null":zero_vwap_count,"zero_volume_open_to_null":sum(len(v) for v in zero_volume.values()),"policy_sha256":sha(root/"normalization-policy.json")},
            "missing_policy":"All503 frozen names and all100 frozen selections retained; exact raw-absence nulls retained; no future-completeness filtering or fill",
            "off_calendar_records":off_calendar,"large_adjusted_close_jumps_threshold_abs_simple_return":.5,"large_adjusted_close_jumps":jumps,
            "identity_attention":identities,
            "limitations":["Capture uses provider asof=2026-09-04 symbol mapping and adjustment=all; historical security identity/adjustments are not independently certified.",
                           "EXE includes predecessor/bankruptcy history concerns; SNDK ticker reuse and spin-offs/merger successors require separate continuity qualification.",
                           "Large close changes are flags only; no price or signal corrections were made.","Current roster and sectors are survivor-selected retrospective diagnostics; historical membership was not applied."],
            "capture_receipt_sha256":sha(root/"capture"/"receipt.json"),"verifier_sha256":sha(Path(__file__))}


if __name__ == "__main__":
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--root",type=Path,required=True);args=ap.parse_args()
    report=verify(args.root)
    with (args.root/"capture-verification.json").open("x") as handle:
        json.dump(report,handle,indent=2,allow_nan=False);handle.write("\n")
    print(json.dumps({k:report[k] for k in ("state","responses_verified","raw_bars_verified","sessions","panel_checks","normalization")},indent=2))
