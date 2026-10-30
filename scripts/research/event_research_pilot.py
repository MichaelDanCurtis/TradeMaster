"""Freeze and capture an original-document pilot without reading return labels.

Public SEC GET requests only. Offline scoring is separate from source capture.
The current-roster sample audits plumbing; it cannot qualify a SPY backtest.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import httpx

from tradingagents.research.filing_stability import (
    VERSION, STOP_WORDS, document_url, normalized_document, original_pairs,
    score_pair, sha_bytes, submission_rows,
)


def now():
    return datetime.now(timezone.utc).isoformat()


def write_new(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return sha_bytes(Path(path).read_bytes())


def check_protocol(root):
    lock = read(root / "protocol-lock.json")
    if digest(root / "protocol.json") != lock["sha256"]:
        raise ValueError("Frozen protocol changed")
    p = read(root / "protocol.json")
    if digest(p["source_universe"]) != p["source_universe_sha256"]:
        raise ValueError("Frozen source universe changed")
    for filename, expected in p["code_hashes"].items():
        if digest(filename) != expected:
            raise ValueError("Frozen research code changed: " + filename)
    return p


def freeze(root, universe):
    u = read(universe)
    groups = {}
    for symbol, cik in u["issuers"].items():
        groups.setdefault(u["sectors"].get(symbol, "Unknown"), []).append(symbol)
    chosen, seen = [], set()
    key = lambda s: sha_bytes(("F1-pilot-v1:" + u["issuers"][s]).encode())
    for sector, symbols in sorted(groups.items()):
        count = 0
        for symbol in sorted(symbols, key=key):
            if u["issuers"][symbol] in seen:
                continue
            chosen.append(symbol); seen.add(u["issuers"][symbol]); count += 1
            if count == 2:
                break
    for symbol in sorted(u["issuers"], key=key):
        if len(chosen) >= 25:
            break
        if u["issuers"][symbol] not in seen:
            chosen.append(symbol); seen.add(u["issuers"][symbol])
    if len(chosen) != 25:
        raise ValueError("Pilot requires 25 distinct issuers")
    code = [Path(__file__).resolve(), Path("tradingagents/research/filing_stability.py").resolve()]
    protocol = {
        "id": "event-research-pilot-v1", "frozen_at": now(), "status": "frozen_data_pilot",
        "source_universe": str(universe.resolve()), "source_universe_sha256": digest(universe),
        "code_hashes": {str(p): digest(p) for p in code},
        "issuer_sample": [{"symbol": s, "cik": u["issuers"][s], "sector_descriptive_only": u["sectors"][s]} for s in chosen],
        "selection": "Two distinct issuers per current sector, then fill to 25 by SHA256(F1-pilot-v1:CIK); no returns used",
        "f1": {"version": VERSION, "new_report_year": 2024, "pairs_per_issuer": 4,
               "expected_pair_slots": 100, "forms": ["10-K", "10-Q"], "amendments": "excluded_not_substituted",
               "comparison": "same DEI fiscal period and consecutive fiscal years; report dates 350-380 days apart",
               "text": "remove tables, hidden XBRL, scripts and styles; lowercase ASCII word sets; fixed stop words",
               "stop_words": sorted(STOP_WORDS), "metric": "Jaccard intersection over union",
               "minimum_distinct_tokens": 500, "minimum_narrative_characters": 10000,
               "historical_availability": "max(acceptance UTC, filing-date 23:59:59 America/New_York), plus five minutes",
               "entry_delay": "two full exchange sessions after availability; never substitute weekday arithmetic",
               "freshness_days": 180, "portfolio_status": "blocked_pending_qualified_historical_universe_and_outcomes",
               "future_primary_portfolio": "quarterly cap-weighted highest-similarity third of historical top-1000 eligible common stocks",
               "future_controls": ["SPY total return", "same-data-eligible cap-weighted universe", "full-universe coverage control"],
               "future_cost_sensitivities_bps_per_side": [11, 22]},
        "o1": {"event_candidates": 20, "selection": "Earliest 2023-2025 Item 2.01 8-K among pilot issuers, ordered filingDate/accession",
               "scope": "Acquisition/disposition candidates, not verified all-cash deals or representative investment cohort",
               "holdings_records": 5, "holdings_selection": "First five distinct 13F-HR filers in 2024Q1 by hash O1-pilot-v1:CIK",
               "cash_receipts": "unknown_until_terms_payment_identity_and_ownership_are_verified",
               "planned_entry": "next session after usable public completion confirmation", "planned_hold_sessions": 10},
        "tenders": {"records": 20, "selection": "Earliest original SC TO-I or SC TO-T in 2024Q1 master index, ordered date/CIK/path",
                    "scope": "Initial-offer source audit; amendments, outcomes, NAV, quotes, broker eligibility remain separate gates"},
        "sec": {"headers": {"User-Agent": "TradeMasterResearch/1.0 personal desktop research", "Accept-Encoding": "gzip, deflate"},
                "minimum_request_spacing_seconds": .6, "workers": 2, "max_attempts": 3,
                "index_url": "https://www.sec.gov/Archives/edgar/full-index/2024/QTR1/master.idx"},
        "prohibitions": ["no return labels in this pilot", "no backdating observed content", "no broker operations",
                         "no survivor-sample performance claim", "no inferred cash terms or missing prices"],
        "promotion": "Data structural validation is not manual semantic audit, investment qualification or evidence of alpha",
        "investment_confirmation": "Freeze complete portfolio protocol on qualified data before opening a separate confirmation sample",
    }
    root.mkdir(parents=True, exist_ok=False)
    (root / "raw").mkdir(); (root / "normalized").mkdir()
    write_new(root / "protocol.json", protocol)
    write_new(root / "protocol-lock.json", {"sha256": digest(root / "protocol.json"), "frozen_at": now()})
    print(json.dumps({"status": "frozen", "issuers": len(chosen), "root": str(root)}), flush=True)


class Capture:
    def __init__(self, root, config):
        self.root, self.config = root, config
        self.lock = threading.Lock(); self.last_request = 0.; self.count = 0
        self.receipt = read(root / "receipt.json") if (root / "receipt.json").exists() else {}
        self.client = httpx.Client(timeout=35, follow_redirects=False, headers=config["headers"])

    def get(self, url):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc not in {"www.sec.gov", "data.sec.gov"}:
            raise ValueError("Only official public SEC sources are permitted")
        key = sha_bytes(url.encode())
        with self.lock:
            old = self.receipt.get(key)
        if old:
            if old.get("sha256"):
                raw = (self.root / old["file"]).read_bytes()
                if sha_bytes(raw) != old["sha256"]:
                    raise ValueError("Captured source changed")
                return raw
            return None
        record = {"url": url, "requested_at": now(), "status": "failed"}
        raw = None
        for attempt in range(self.config["max_attempts"]):
            with self.lock:
                time.sleep(max(0, self.config["minimum_request_spacing_seconds"] - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
            try:
                with self.client.stream("GET", url) as response:
                    record["http_status"] = response.status_code
                    record["content_type"] = response.headers.get("content-type")
                    if response.status_code == 200:
                        chunks, length = [], 0
                        for chunk in response.iter_bytes():
                            length += len(chunk)
                            if length > 64 * 1024 * 1024:
                                raise ValueError("Source exceeds pilot size limit")
                            chunks.append(chunk)
                        raw = b"".join(chunks)
                        record["status"] = "captured"
                    if response.status_code not in {429, 500, 502, 503, 504}:
                        break
            except (httpx.HTTPError, ValueError) as exc:
                record["error_type"] = type(exc).__name__
            if attempt + 1 < self.config["max_attempts"]:
                time.sleep(2 * (attempt + 1))
        record["retrieved_at"] = now()
        if raw is not None:
            filename = f"raw/{key}.bin"
            with (self.root / filename).open("xb") as handle:
                handle.write(raw)
            record.update(file=filename, sha256=sha_bytes(raw), bytes=len(raw))
        with self.lock:
            self.receipt[key] = record; self.count += 1
            tmp = self.root / "receipt.tmp"
            tmp.write_text(json.dumps(self.receipt, indent=2) + "\n")
            tmp.replace(self.root / "receipt.json")
            if self.count % 10 == 0:
                print(json.dumps({"new_requests": self.count, "captured": sum(r["status"] == "captured" for r in self.receipt.values())}), flush=True)
        return raw

    def close(self):
        self.client.close()


def parse_master(raw):
    rows = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        fields = line.split("|")
        if len(fields) != 5 or not fields[0].isdigit():
            continue
        cik, name, form, filed, path = fields
        if not re.fullmatch(r"edgar/data/\d+/\d{10}-\d{2}-\d{6}\.txt", path):
            continue
        rows.append({"cik": cik.zfill(10), "issuer_name": name, "form": form,
                     "filingDate": filed, "path": path, "accessionNumber": Path(path).stem})
    if not rows:
        raise ValueError("No valid records in master index")
    return rows


def capture(root):
    p = check_protocol(root); c = Capture(root, p["sec"])
    try:
        if (root / "selection-lock.json").exists():
            selected = read(root / "selections.json")
            if digest(root / "selections.json") != read(root / "selection-lock.json")["sha256"]:
                raise ValueError("Frozen selections changed")
        else:
            def issuer_rows(issuer):
                cik = issuer["cik"]
                raw = c.get(f"https://data.sec.gov/submissions/CIK{cik}.json")
                if raw is None:
                    return []
                payload = json.loads(raw)
                if int(payload["cik"]) != int(cik):
                    raise ValueError("Submissions issuer mismatch")
                rows = submission_rows(payload, cik)
                for older in payload["filings"].get("files", []):
                    if older["filingTo"] < "2023-01-01" or older["filingFrom"] > "2025-12-31":
                        continue
                    name = older["name"]
                    if not re.fullmatch(r"CIK\d{10}-submissions-\d+\.json", name):
                        raise ValueError("Unexpected submissions history file")
                    history = c.get("https://data.sec.gov/submissions/" + name)
                    if history is not None:
                        rows += submission_rows(json.loads(history), cik)
                return rows
            with ThreadPoolExecutor(max_workers=p["sec"]["workers"]) as pool:
                all_rows = [r for group in pool.map(issuer_rows, p["issuer_sample"]) for r in group]
            # De-duplicate overlap between current and historical submission files.
            by_id = {}
            for r in all_rows:
                key = r["accessionNumber"]
                if key in by_id and by_id[key] != r:
                    raise ValueError("Conflicting accession metadata")
                by_id[key] = r
            all_rows = list(by_id.values())
            pairs = original_pairs(all_rows, report_year=p["f1"]["new_report_year"])
            events = sorted((r for r in all_rows if r["form"] == "8-K" and "2.01" in r["items"].split(",")
                             and "2023-01-01" <= r["filingDate"] <= "2025-12-31"),
                            key=lambda r: (r["filingDate"], r["accessionNumber"]))[:p["o1"]["event_candidates"]]
            index = c.get(p["sec"]["index_url"])
            master = parse_master(index) if index else []
            offers = sorted((r for r in master if r["form"] in {"SC TO-I", "SC TO-T"}),
                            key=lambda r: (r["filingDate"], r["cik"], r["path"]))[:p["tenders"]["records"]]
            holders, seen = [], set()
            for r in sorted((r for r in master if r["form"] == "13F-HR"),
                            key=lambda r: (sha_bytes(("O1-pilot-v1:" + r["cik"]).encode()), r["filingDate"], r["path"])):
                if r["cik"] not in seen:
                    holders.append(r); seen.add(r["cik"])
                if len(holders) == p["o1"]["holdings_records"]:
                    break
            selected = {"frozen_at": now(), "pairs": pairs, "cash_event_candidates": events,
                        "offer_records": offers, "holdings_records": holders,
                        "metadata_rows": len(all_rows), "master_rows": len(master)}
            write_new(root / "selections.json", selected)
            write_new(root / "selection-lock.json", {"sha256": digest(root / "selections.json"), "frozen_at": now()})
        urls = set()
        for pair in selected["pairs"]:
            for record in [pair["new"], pair["old"]]:
                if record:
                    urls.add(document_url(record))
        urls.update(document_url(r) for r in selected["cash_event_candidates"])
        urls.update("https://www.sec.gov/Archives/" + r["path"] for r in selected["offer_records"] + selected["holdings_records"])
        with ThreadPoolExecutor(max_workers=p["sec"]["workers"]) as pool:
            list(pool.map(c.get, sorted(urls)))
        print(json.dumps({"status": "capture_finished", "selected_pairs": len(selected["pairs"]),
                          "cash_candidates": len(selected["cash_event_candidates"]), "offers": len(selected["offer_records"]),
                          "holdings_filings": len(selected["holdings_records"]), "requests": len(c.receipt),
                          "failures": sum(r["status"] != "captured" for r in c.receipt.values())}), flush=True)
    finally:
        c.close()


def score(root):
    p = check_protocol(root)
    selected, receipt = read(root / "selections.json"), read(root / "receipt.json")
    if digest(root / "selections.json") != read(root / "selection-lock.json")["sha256"]:
        raise ValueError("Frozen selections changed")
    by_url = {r["url"]: r for r in receipt.values()}
    def raw_for(url):
        r = by_url.get(url, {})
        if r.get("status") != "captured":
            return None
        raw = (root / r["file"]).read_bytes()
        if sha_bytes(raw) != r["sha256"]:
            raise ValueError("Raw source changed")
        return raw
    cache, results = {}, []
    for pair in selected["pairs"]:
        result = {"new": pair["new"], "old": pair["old"]}
        docs = []
        for r in [pair["new"], pair["old"]]:
            raw = raw_for(document_url(r)) if r else None
            if raw is None:
                docs.append(None); continue
            key = sha_bytes(raw)
            if key not in cache:
                cache[key] = normalized_document(raw)
                destination = root / "normalized" / (key + ".json")
                if destination.exists():
                    if read(destination) != cache[key]:
                        raise ValueError("Normalized source changed")
                else:
                    write_new(destination, cache[key])
            docs.append(cache[key])
        if any(d is None for d in docs):
            result.update(status="unqualified", issues=pair["metadata_issues"] + ["missing_original_source"], jaccard=None)
        else:
            result.update(score_pair(pair, *docs))
            result["raw_hashes"] = [d["raw_sha256"] for d in docs]
        results.append(result)
        if len(results) % 10 == 0:
            print(json.dumps({"pairs_scored": len(results)}), flush=True)
    events = []
    for record in selected["cash_event_candidates"]:
        raw = raw_for(document_url(record))
        text = normalized_document(raw)["preview"] if raw else ""
        events.append({**record, "source_captured": raw is not None, "preview": text,
                       "cash_terms_verified": False, "payment_date_verified": False,
                       "status": "requires_terms_and_transaction_identity_audit"})
    holdings = []
    for record in selected["holdings_records"]:
        raw = raw_for("https://www.sec.gov/Archives/" + record["path"])
        row = {**record, "source_captured": raw is not None, "ownership_scope": "manager_aggregate_proxy"}
        if raw:
            xmls = re.findall(rb"<XML>\s*(.*?)\s*</XML>", raw, re.S | re.I)
            positions, report_periods, parse_errors = [], [], []
            for xml in xmls:
                try:
                    tree = ET.fromstring(xml)
                except ET.ParseError:
                    parse_errors.append("malformed_xml_segment")
                    continue
                for node in tree.iter():
                    tag = node.tag.split("}")[-1]
                    if tag == "periodOfReport" and node.text:
                        report_periods.append(node.text)
                    if tag == "infoTable":
                        fields = {n.tag.split("}")[-1]: n.text for n in node.iter() if n.text and n.text.strip()}
                        positions.append({k: fields.get(k) for k in ["nameOfIssuer", "cusip", "value", "sshPrnamt", "sshPrnamtType", "putCall"]})
            row.update(report_periods=report_periods, positions_count=len(positions), positions=positions,
                       parse_errors=parse_errors, holdings_parse_complete=bool(positions) and not parse_errors,
                       values_scope="raw reported units; no dollar conversion or inferred fund holdings",
                       historical_availability="filing date only in master; acceptance/header audit still required")
        holdings.append(row)
    offers = [{**r, "source_captured": raw_for("https://www.sec.gov/Archives/" + r["path"]) is not None,
               "terms_verified": False, "outcome_verified": False, "broker_eligibility_verified": False}
              for r in selected["offer_records"]]
    report = {"created_at": now(), "protocol_sha256": digest(root / "protocol.json"),
              "selection_sha256": digest(root / "selections.json"), "receipt_sha256": digest(root / "receipt.json"),
              "f1": {"expected_slots": p["f1"]["expected_pair_slots"], "selected_pairs": len(results),
                     "unfilled_slots": p["f1"]["expected_pair_slots"] - len(results),
                     "status_counts": dict(Counter(r["status"] for r in results)),
                     "issue_counts": dict(Counter(i for r in results for i in r["issues"])), "pairs": results},
              "o1": {"events": events, "holdings": holdings, "return_test_status": "not_run_unqualified_cash_receipts_and_ownership_graph"},
              "tenders": {"offers": offers, "return_test_status": "not_run_unverified_terms_outcomes_quotes_and_broker_capability"},
              "investment_status": "not_qualified_for_SPY_comparison",
              "blocking_gaps": ["Historical top-1000 security universe, lagged capitalizations and terminal outcomes not qualified",
                                "Pilot chosen from 2026 survivors; sector labels are contemporary descriptions",
                                "Original-source structural checks do not replace manual extraction audit",
                                "Full chronological portfolio protocol and independent confirmation sample not yet frozen"],
              "returns_or_order_activity": "none"}
    write_new(root / "audit.json", report)
    manifest = {str(f.relative_to(root)): digest(f) for f in sorted(root.rglob("*")) if f.is_file()}
    write_new(root / "manifest.json", {"created_at": now(), "files": manifest})
    print(json.dumps({"f1": {k: v for k, v in report["f1"].items() if k != "pairs"},
                      "holdings_rows": sum(r.get("positions_count", 0) for r in holdings),
                      "investment_status": report["investment_status"]}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["freeze", "capture", "score"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--universe", type=Path, default=Path(".research-artifacts/prediction-wide-2026-09-07/universe.json"))
    a = parser.parse_args()
    if a.mode == "freeze":
        freeze(a.root, a.universe)
    elif a.mode == "capture":
        capture(a.root)
    else:
        score(a.root)


if __name__ == "__main__":
    main()
