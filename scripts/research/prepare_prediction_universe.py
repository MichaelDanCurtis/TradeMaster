"""Capture public constituent data without executing downloaded code.

The output is a community historical reconstruction with source hashes, not
licensed official point-in-time index data or a security-master mapping.
"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import urllib.parse
import urllib.request

REVISION = "a2430f2af0c79ddf0748e91de11bdeb1616ab5a7"
FILES = {
    "current.csv": "sp500.csv",
    "historical.csv": "S&P 500 Historical Components & Changes (Updated).csv",
    "changes.csv": "sp500_changes_since_2019.csv",
    "ticker-intervals.csv": "sp500_ticker_start_end.csv",
    "README.md": "README.md", "LICENSE": "LICENSE",
}
PRIMARY = {
    "sp-20260813.html": "https://press.spglobal.com/2026-08-13-Reddit-Set-to-Join-S-P-500-and-Sun-Communities-to-Join-S-P-MidCap-400",
    "sp-20260904.html": "https://press.spglobal.com/2026-09-04-Bloom-Energy,-Illumina,-and-Everpure-Set-to-Join-S-P-500-Others-to-Join-S-P-100,-S-P-MidCap-400,-and-S-P-SmallCap-600",
    "alias-meta.html": "https://investor.atmeta.com/investor-news/press-release-details/2022/Meta-Platforms-Inc.-to-Change-Ticker-Symbol-to-META-on-June-9/default.aspx",
    "alias-wtw.html": "https://investors.wtwco.com/news-releases/news-release-details/willis-towers-watson-announces-nasdaq-ticker-symbol-change-wltw",
    "alias-ball.html": "https://www.ball.com/newswire/article/124123/ball-board-declares-quarterly-dividend-stock-ticker-symbol-changing-to-ball",
    "alias-elv.html": "https://www.elevancehealth.com/newsroom/elevance-health-rings-in-rebrand-with-nyse-opening-bell",
}
FALLBACK = {
    "alias-wtw.html": ("alias-wtw.pdf", "https://investors.wtwco.com/node/24111/pdf"),
    "alias-ball.html": ("alias-ball.pdf", "https://investors.ball.com/sec-filings/all-sec-filings/content/0000009389-22-000014/0000009389-22-000014.pdf"),
}
ALIASES = [
    {"old": "FB", "new": "META", "effective_date": "2022-06-09", "source_file": "alias-meta.html"},
    {"old": "WLTW", "new": "WTW", "effective_date": "2022-01-10", "source_file": "alias-wtw.html"},
    {"old": "BLL", "new": "BALL", "effective_date": "2022-05-10", "source_file": "alias-ball.html"},
    {"old": "ANTM", "new": "ELV", "effective_date": "2022-06-28", "source_file": "alias-elv.html"},
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ConstituentsTable(HTMLParser):
    def __init__(self):
        super().__init__(); self.active = False; self.cell = None; self.row = []; self.rows = []
    def handle_starttag(self, tag, attrs):
        if tag == "table" and dict(attrs).get("id") == "constituents": self.active = True
        if self.active and tag == "tr": self.row = []
        if self.active and tag in ("td", "th"): self.cell = []
    def handle_data(self, data):
        if self.active and self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if self.active and tag in ("td", "th") and self.cell is not None:
            self.row.append("".join(self.cell).strip()); self.cell = None
        if self.active and tag == "tr": self.rows.append(self.row)
        if tag == "table": self.active = False


def finalize_sources(root, proposal, manifest):
    """Can finalize captured sources without refetching or changing roster bytes."""
    for alias in proposal["ticker_aliases"]:
        original = alias["source_file"]
        source = next(r for r in manifest if r["file"] == original)
        if "sha256" not in source and original in FALLBACK:
            filename, url = FALLBACK[original]
            capture(root, filename, url, manifest, required=False)
            fallback = next(r for r in manifest if r["file"] == filename)
            if "sha256" in fallback:
                alias["source_file"] = filename; source = fallback
        alias["url"] = source["url"]
        alias["source_capture_state"] = "captured" if "sha256" in source else "unavailable"
        alias["scope"] = "Issuer verified rename; historical price-provider stitching/identity remains unverified"
    if (root/"wikipedia.html").exists():
        wiki = (root/"wikipedia.html").read_text()
        parser = ConstituentsTable(); parser.feed(wiki)
        rows = parser.rows[1:]
        wiki_symbols = [r[0] for r in rows]
        revision = re.search(r'"wgRevisionId":(\d+)', wiki)
        assert len(wiki_symbols) == len(set(wiki_symbols)) == 503
        assert set(wiki_symbols) == set(proposal["current_symbols"])
        proposal["wikipedia_check"] = {"revision": revision.group(1) if revision else None,
                                       "count": len(wiki_symbols), "symbol_sets_match": True,
                                       "scope": "Cross-check of underlying community source, not independent official corroboration"}
    symbols = proposal["current_symbols"]
    proposal["current_unique_cik_count"] = len({r["cik"] for r in proposal["current_members"]})
    proposal["selected_primary_event_checks"] = [
        {"announcement_date": "2026-08-13", "effective_date": "2026-08-18", "add": ["RDDT"], "remove": ["AVB"], "source_file": "sp-20260813.html",
         "membership_check": "RDDT present and AVB absent in cutoff roster", "passed": "RDDT" in symbols and "AVB" not in symbols},
        {"announcement_date": "2026-09-04", "effective_date": "2026-09-21", "source_file": "sp-20260904.html",
         "future_additions": ["BE", "P", "ILMN"], "future_deletions": ["TAP", "TTD", "BLDR"],
         "membership_check": "Future additions absent and future deletions still present at Sep4 cutoff",
         "passed": not set(["BE", "P", "ILMN"]) & set(symbols) and set(["TAP", "TTD", "BLDR"]) <= set(symbols)},
    ]
    assert all(r["passed"] for r in proposal["selected_primary_event_checks"])
    proposal["sources"] = [{"file": r["file"], "sha256": r.get("sha256"), "url": r["url"]} for r in manifest]
    (root/"universe.json").write_text(json.dumps(proposal, indent=2)+"\n")
    (root/"sources.json").write_text(json.dumps(manifest, indent=2)+"\n")


def capture(root, filename, url, manifest, required=True):
    request = urllib.request.Request(url, headers={"User-Agent": "TradeMasterResearch/1.0 public-source-capture"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            item = {"file": filename, "url": url, "final_url": response.url,
                    "sha256": sha(raw), "bytes": len(raw),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified")}
        (root/filename).write_bytes(raw)
        manifest.append(item)
        return raw
    except Exception as exc:
        manifest.append({"file": filename, "url": url, "error": f"{type(exc).__name__}: {exc}"})
        if required:
            raise
        return None


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    manifest = []
    commit = json.loads(capture(root, "commit.json", f"https://api.github.com/repos/fja05680/sp500/commits/{REVISION}", manifest))
    assert commit["sha"] == REVISION
    content = {}
    for filename, remote in FILES.items():
        url = f"https://raw.githubusercontent.com/fja05680/sp500/{REVISION}/" + urllib.parse.quote(remote)
        content[filename] = capture(root, filename, url, manifest)
    current = list(csv.DictReader(io.StringIO(content["current.csv"].decode())))
    history = list(csv.DictReader(io.StringIO(content["historical.csv"].decode())))
    assert [r["date"] for r in history] == sorted(set(r["date"] for r in history))
    current_members = [{"symbol": r["Symbol"], "security": r["Security"], "sector": r["GICS Sector"],
                        "sub_industry": r["GICS Sub-Industry"], "cik": r["CIK"].zfill(10),
                        "date_added_reported": r["Date added"], "headquarters": r["Headquarters Location"]}
                       for r in current]
    symbols = [r["symbol"] for r in current_members]
    assert len(symbols) == len(set(symbols)) == 503
    assert len({r["sector"] for r in current_members}) == 11
    cutoff = "2026-09-04"
    relevant = [r for r in history if r["date"] <= cutoff]
    assert set(symbols) == set(relevant[-1]["tickers"].split(","))
    baseline = max((r for r in relevant if r["date"] < "2016-01-01"), key=lambda r: r["date"])
    records = [baseline] + [r for r in relevant if r["date"] >= "2016-01-01"]
    snapshots = [{"date": r["date"], "symbols": r["tickers"].split(",")} for r in records]
    assert all(len(r["symbols"]) == len(set(r["symbols"])) for r in snapshots)
    events = []
    for before, after in zip(snapshots, snapshots[1:]):
        removed = sorted(set(before["symbols"])-set(after["symbols"]))
        added = sorted(set(after["symbols"])-set(before["symbols"]))
        if removed or added:
            events.append({"effective_date_reported": after["date"], "add": added, "remove": removed,
                           "previous_snapshot": before["date"]})
    union = sorted({s for row in snapshots for s in row["symbols"]})
    limitations = [
        "Community-maintained reconstruction, not licensed official point-in-time S&P membership or independently verified complete history.",
        "Current roster and sectors were retrieved in September 2026; using them to select historical stocks has survivorship/selection bias.",
        "Current GICS sectors are descriptive only, not dated historical sector assignments. Historical members may lack sector/CIK metadata here.",
        "Historical snapshot dates are treated as reported effective dates, not announcement or first-publication timestamps; not all dates independently verified.",
        "Multiple share classes are distinct securities, so 503 securities does not mean 503 distinct companies.",
        "Symbol changes and mergers require security identity review; no blanket old-to-current ticker substitution is authorized by this dataset.",
        "Delisted prices and terminal merger payouts may be missing from providers. Record all missing requested securities/dates; do not silently exclude failures or carry stale prices indefinitely.",
        "Repository warning: early history has incomplete counts; requested post-2016 history has only structural and selected-event checks here.",
    ]
    proposal = {"state": "public_reconstruction", "cutoff_date": cutoff, "github_revision": REVISION,
                "github_committed_at": commit["commit"]["committer"]["date"],
                "current_members": current_members, "current_symbols": symbols,
                "current_sector_counts": dict(sorted(Counter(r["sector"] for r in current_members).items())),
                "current_count": len(symbols), "source_latest_snapshot_date": relevant[-1]["date"],
                "historical_snapshots": snapshots, "historical_events": events,
                "historical_union_symbols": union,
                "historical_only_symbols": sorted(set(union)-set(symbols)),
                "historical_coverage": {"baseline_snapshot_date": baseline["date"], "requested_start": "2016-01-01",
                                        "requested_end": cutoff, "last_change_snapshot": relevant[-1]["date"],
                                        "snapshot_count": len(snapshots), "changed_snapshot_count": len(events),
                                        "union_symbol_count": len(union), "minimum_member_count": min(len(r["symbols"]) for r in snapshots),
                                        "maximum_member_count": max(len(r["symbols"]) for r in snapshots)},
                "ticker_aliases": ALIASES,
                "ticker_format": {"preserve": "Raw dots preserved, including BRK.B/BF.B; adapter is responsible for provider syntax", "automatic_alias_stitching": False},
                "limitations": limitations}
    # Publish the data required for a separate price capture before slower optional source captures.
    (root/"universe.json").write_text(json.dumps(proposal, indent=2)+"\n")
    (root/"sources.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps({"phase": "roster_ready", "file": str(root/"universe.json"), "counts": proposal["historical_coverage"]}), flush=True)
    for filename, url in PRIMARY.items():
        capture(root, filename, url, manifest, required=False)
    capture(root, "wikipedia.html", "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", manifest, required=False)
    finalize_sources(root, proposal, manifest)
    print(json.dumps({"phase": "complete", "current_count": len(symbols), "historical_union": len(union),
                      "optional_capture_failures": [r["file"] for r in manifest if "error" in r]}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    prepare(ap.parse_args().output)
