"""Independently reconstruct a saved prediction panel from its raw GET receipts.

Does not import the capture builder, fetch data, repair prices, or filter symbols.
Large-return flags are diagnostics only and do not alter the frozen experiment.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def verify(root):
    intent = json.loads((root / "protocol.json").read_text())
    receipt = json.loads((root / "capture-receipt.json").read_text())
    panel = json.loads((root / "panel.json").read_text())
    checks, errors, warnings = [], [], []

    def check(name, passed, detail=None):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        if not passed:
            errors.append(name)

    check("capture_complete", receipt.get("complete") is True)
    check("protocol_sha256", digest(root / "protocol.json") == receipt["protocol_sha256"])
    check("panel_sha256", digest(root / "panel.json") == receipt["panel_sha256"])
    names = intent["symbols"] + [intent["benchmark"]]
    check("frozen_symbol_order", panel["symbols"] == intent["symbols"] and panel["benchmark"] == intent["benchmark"])
    check("unique_symbols", len(names) == len(set(names)))
    payloads = []
    capture_times = []
    paths = []
    raw_checks = []
    for entry in receipt["responses"]:
        path = (root / entry["file"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Receipt path escapes capture root")
        raw = path.read_bytes()
        matched = hashlib.sha256(raw).hexdigest() == entry["sha256"] and len(raw) == entry["bytes"]
        check("raw_receipt:" + entry["file"], matched)
        raw_checks.append({"file": entry["file"], "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "matched": matched})
        capture_times.append(instant(entry["captured_at"]))
        paths.append(entry["file"])
        payloads.append(json.loads(raw))
    check("unique_raw_paths", len(paths) == len(set(paths)))
    check("recorded_protocol_declaration_precedes_every_response", all(instant(intent["declared_at"]) < t for t in capture_times))
    check("response_times_nondecreasing", capture_times == sorted(capture_times))
    check("all_saved_raw_files_receipted", set(paths) == {str(p.relative_to(root)) for p in (root / "raw").glob("*.json")})
    calendar_entries = [(e, p) for e, p in zip(receipt["responses"], payloads) if e["url"] == "https://paper-api.alpaca.markets/v2/calendar"]
    check("one_calendar_response", len(calendar_entries) == 1)
    if len(calendar_entries) != 1:
        raise ValueError("Exactly one calendar response required")
    calendar_entry, calendar = calendar_entries[0]
    check("calendar_requested_range", calendar_entry["params"] == {"start": intent["requested_start"], "end": intent["end"]})
    sessions = [r["date"] for r in calendar]
    check("raw_calendar_unique_sorted", sessions == sorted(set(sessions)))
    check("calendar_covers_requested_end", sessions[-1] == intent["end"])
    pages = [(e, p) for e, p in zip(receipt["responses"], payloads) if e["url"] == "https://data.alpaca.markets/v2/stocks/bars"]
    check("only_expected_source_urls", len(pages) + 1 == len(payloads))
    expected_params = {"symbols": ",".join(names), "start": intent["requested_start"],
                       "end": intent["end"] + "T23:59:59Z", "limit": 10000, "sort": "asc", **intent["data"]}
    previous_token = None
    token_values = []
    records = {symbol: {} for symbol in names}
    raw_count = 0
    duplicates = []
    price_violations = []
    vwap_outside_range = []
    time_violations = []
    fields = (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v"), ("vwap", "vw"))
    for page_index, (entry, payload) in enumerate(pages):
        params = dict(entry["params"])
        token = params.pop("page_token", None)
        check(f"page_{page_index}_request_matches_protocol", params == expected_params)
        check(f"page_{page_index}_pagination_chain", token == previous_token)
        if page_index and token is None:
            check(f"page_{page_index}_has_continuation", False)
        if token is not None:
            token_values.append(token)
        previous_token = payload.get("next_page_token")
        for symbol, bars in payload["bars"].items():
            if symbol not in records:
                raise ValueError("Unexpected raw symbol: " + symbol)
            for bar in bars:
                raw_count += 1
                local = instant(bar["t"]).astimezone(ZoneInfo("America/New_York"))
                day = local.date().isoformat()
                if (local.hour, local.minute, local.second) != (0, 0, 0):
                    time_violations.append({"symbol": symbol, "timestamp": bar["t"]})
                row = {field: float(bar[key]) for field, key in fields}
                if day in records[symbol]:
                    duplicates.append({"symbol": symbol, "date": day})
                records[symbol][day] = row
                finite = all(math.isfinite(v) for v in row.values())
                positive = finite and all(v >= 0 if k == "volume" else v > 0 for k, v in row.items())
                ohlc = finite and row["low"] <= min(row["open"], row["close"]) + 1e-6 and row["high"] + 1e-6 >= max(row["open"], row["close"])
                if not positive or not ohlc:
                    price_violations.append({"symbol": symbol, "date": day, "values": row})
                if finite and (row["vwap"] < row["low"] - 1e-6 or row["vwap"] > row["high"] + 1e-6):
                    vwap_outside_range.append({"symbol": symbol, "date": day, "low": row["low"], "high": row["high"], "vwap": row["vwap"]})
    check("pagination_terminal", previous_token is None)
    check("pagination_no_repeated_token", len(token_values) == len(set(token_values)))
    check("raw_bar_count", raw_count == receipt["bar_count"])
    check("no_duplicate_symbol_dates", not duplicates, duplicates)
    check("raw_values_finite_positive_and_ohlc_consistent", not price_violations, price_violations)
    check("daily_timestamps_are_new_york_midnight", not time_violations, time_violations)
    if any(not values for values in records.values()):
        raise ValueError("Missing entire symbol history")
    start = max(min(values) for values in records.values())
    expected_dates = [d for d in sessions if start <= d <= intent["end"]]
    check("common_calendar_dates_exact", panel["dates"] == expected_dates)
    check("session_count", len(expected_dates) == receipt["sessions"])
    missing = {s: [d for d in expected_dates if d not in records[s]] for s in names}
    check("no_interior_missing_bars", not any(missing.values()), {s: v for s, v in missing.items() if v})
    differences = []
    compared = 0
    for symbol in names:
        for field, _ in fields:
            expected = [records[symbol][d][field] for d in expected_dates]
            actual = panel["series"][symbol][field]
            if len(actual) != len(expected):
                differences.append({"symbol": symbol, "field": field, "issue": "length"})
                continue
            for idx, (a, b) in enumerate(zip(actual, expected)):
                compared += 1
                if a != b:
                    differences.append({"symbol": symbol, "field": field, "date": expected_dates[idx], "panel": a, "raw": b})
    check("independent_raw_to_panel_numeric_reconstruction_exact", not differences, {"compared_values": compared, "differences": differences[:20]})
    coverage = {"first_dates": {s: min(records[s]) for s in names}, "last_dates": {s: max(records[s]) for s in names},
                "excluded_outside_common_calendar": {s: len(set(records[s]) - set(expected_dates)) for s in names}, "missing_count": sum(len(v) for v in missing.values())}
    check("coverage_metadata_reconstructed", panel["coverage"] == coverage)
    check("limitations_preserved", panel["limitations"] == intent["limitations"])
    eval_index = next(i for i, d in enumerate(expected_dates) if d >= intent["evaluation_start"])
    mature_train_origins = [t for t in range(252, eval_index, 21) if t + 22 <= eval_index]
    check("declared_training_history_minimum", eval_index >= 252 and len(mature_train_origins) >= 24,
          {"evaluation_index": eval_index, "mature_training_origins": len(mature_train_origins)})
    diagnostics = []
    large_moves = []
    ratio_flags = []
    for symbol in names:
        rows = [records[symbol][d] for d in expected_dates]
        returns = [(rows[i]["close"] / rows[i - 1]["close"] - 1, i) for i in range(1, len(rows))]
        gaps = [(rows[i]["open"] / rows[i - 1]["close"] - 1, i) for i in range(1, len(rows))]
        largest = sorted(returns, key=lambda r: abs(r[0]), reverse=True)
        diagnostics.append({"symbol": symbol, "bars": len(rows), "first": expected_dates[0], "last": expected_dates[-1],
                            "close_min": min(r["close"] for r in rows), "close_max": max(r["close"] for r in rows),
                            "zero_volume_days": sum(r["volume"] == 0 for r in rows),
                            "largest_absolute_close_returns": [{"date": expected_dates[i], "return": value} for value, i in largest[:3]],
                            "largest_absolute_open_gap": max(abs(value) for value, _ in gaps)})
        for value, i in returns:
            if abs(value) > .25:
                large_moves.append({"symbol": symbol, "date": expected_dates[i], "close_return": value})
            ratio = value + 1
            if ratio < .5 or ratio > 2:
                ratio_flags.append({"symbol": symbol, "date": expected_dates[i], "close_ratio": ratio})
    unavailable_prefix = [d for d in sessions if d < start]
    if unavailable_prefix:
        warnings.append(f"Requested history begins {intent['requested_start']}; every series actually begins {start}. {len(unavailable_prefix)} earlier calendar sessions unavailable; the predeclared common-start rule was applied.")
    if large_moves:
        warnings.append(f"{len(large_moves)} daily absolute close returns exceed 25%; retained unchanged for review, not evidence by itself of erroneous adjustment.")
    if vwap_outside_range:
        warnings.append(f"{len(vwap_outside_range)} VWAP values lie outside OHLC range; retained unchanged and listed for review.")
    if ratio_flags:
        warnings.append(f"{len(ratio_flags)} close ratios outside [0.5,2] require adjustment review; no automatic repair.")
    return {"verified_at": datetime.now(timezone.utc).isoformat(), "status": "passed_with_caveats" if not errors else "failed",
            "verifier_sha256": digest(Path(__file__)), "capture_script_sha256_now": digest(Path(__file__).with_name("capture_prediction_panel.py")),
            "protocol_sha256": digest(root / "protocol.json"), "panel_sha256": digest(root / "panel.json"),
            "capture_receipt_sha256": digest(root / "capture-receipt.json"), "checks": checks, "errors": errors,
            "raw_receipts": raw_checks, "numeric_values_compared": compared, "bar_count": raw_count, "sessions": len(expected_dates),
            "stocks": len(intent["symbols"]), "benchmark": intent["benchmark"], "actual_start": start, "actual_end": expected_dates[-1],
            "warnings": warnings, "large_move_threshold_absolute_return": .25, "large_moves": large_moves,
            "potential_unadjusted_split_ratio_flags": ratio_flags, "vwap_outside_range": vwap_outside_range, "per_symbol": diagnostics,
            "interpretation": ["Independent raw-to-panel reconstruction and file integrity verified; not independent market-price accuracy verification.",
                               "Protocol hash and recorded local timestamps support declaration-before-capture; no externally trusted timestamp or immutable audit service attests to that ordering.",
                               "Capture source currently writes protocol before GET calls and follows read-only GET interfaces; no original executed-script hash was stored in capture receipt.",
                               "Retrospective all-adjusted prices, current survivors, and hypothetical executable opens remain material research limitations.",
                               "No symbol removal, price correction, model selection or model-performance inspection occurred in this audit."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = verify(args.capture)
    with args.output.open("x") as out:
        json.dump(report, out, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({"status": report["status"], "checks": len(report["checks"]), "errors": report["errors"],
                      "numeric_values_compared": report["numeric_values_compared"], "warnings": report["warnings"]}))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
