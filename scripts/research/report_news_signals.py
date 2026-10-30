"""Generate a source-linked research report and verify the saved evidence."""
import argparse
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from scripts.research.build_news_signals import sha, load_verified


def main(root):
    source, tones = load_verified(root / "history")
    result = json.loads((root / "diagnostic.json").read_text())
    receipt = json.loads((root / "history/receipt.json").read_text())
    lock = json.loads((root / "diagnostic-lock.json").read_text())
    protocol = json.loads((root / "protocol.json").read_text())
    if result["lock_sha256"] != sha(root / "diagnostic-lock.json"):
        raise ValueError("Diagnostic lock changed")
    for name, expected in lock["input_sha256"].items():
        if sha(root / name) != expected:
            raise ValueError("News input changed")
    for name, expected in lock["code_sha256"].items():
        if sha(Path(name)) != expected:
            raise ValueError("Diagnostic code changed")
    if sha(Path(protocol["price_source"])) != lock["panel_sha256"]:
        raise ValueError("Price evidence changed")
    tests = ET.parse(root / "unit-tests.xml").getroot()
    suites = list(tests.iter("testsuite"))
    passed = sum(int(s.attrib.get("tests", 0)) for s in suites)
    if any(int(s.attrib.get(k, 0)) for s in suites for k in ["failures", "errors", "skipped"]):
        raise ValueError("Tests are not all passing")
    yearly = "\n".join(f"| {r['year']} | {r['observations']} | {r['pooled_spearman']:.4f} | {r['mean_weekly_spearman']:.4f} |" for r in result["by_year"])
    snapshots = json.loads((root / "historical-snapshots.json").read_text())
    per_symbol = []
    for symbol in protocol["symbols"]:
        articles = [a for a in source["articles"] if symbol in a["symbols"]]
        records = [r for r in result["rows"] if r["symbol"] == symbol]
        per_symbol.append(f"| {symbol} | {len(articles)} | {sum(len(a['symbols']) == 1 for a in articles)} | {len(records)} |")
    web = json.loads((root / "web-agent/evidence.json").read_text())
    links = "\n".join(f"- [{r['article']['symbols'][0]}]({r['article']['url']}): {r['evidence']['event_type']}, {r['evidence']['direction']} financial direction; published {r['article']['publication_date']}, retrieved during this run."
                      for r in web["records"] if r["status"] == "verified_excerpt")
    report = f"""# News research: working pipeline, no demonstrated sentiment edge

The new pipeline collected real news, quantified text locally on Apple MPS/Metal,
and ran a historical diagnostic. Generic headline tone had essentially zero
pooled association with subsequent five-session excess return over SPY in both
years. This is evidence against using this particular simple sentiment feature
on its own in this sample; it does not rule out more specific news-event signals.

## Historical diagnostic

| Entry year | Stock-week observations | Pooled Spearman correlation | Mean within-week Spearman |
|---|---:|---:|---:|
{yearly}

Zero correlation means no monotonic relationship in this sample. These are
descriptive statistics, not independent significance tests. No trading portfolio,
transaction-cost return, risk-adjusted alpha or probability of profit is claimed.

The frozen rule uses seven days of deduplicated single-ticker headline tone
before the preceding session's actual close (including half days). A story is
usable only strictly after its latest publication/revision time plus 15 minutes.
Return measurement starts at the first session opening each ISO week and ends
five sessions later; SPY uses the same timestamps and existing adjusted prices.
The tone is P(positive text label) minus P(negative text label), not a return forecast.

## Captured evidence and Mac execution

- Requested archive: {receipt['query']['start']} through {receipt['query']['end']}.
- {len(receipt['pages'])} successful paginated responses; {receipt['article_count']:,} received articles.
- {len(source['articles']):,} normalized articles; {len(source['quarantine'])} quarantined because at least one ticker tag was unsupported. No guessed aliases.
- {len(tones['records']):,} single-ticker headlines classified with {tones['model']} at commit `{tones['revision']}`.
- Inference ran on `{tones['device']}` using torch {tones['torch']}; no article text sent to an external AI API.
- {len(snapshots):,} dated stock snapshots; {len(result['rows']):,} usable stock-week observations and {len(result['excluded'])} missing-tone exclusions. No missing-price exclusions.
- {len(result['causal_replays']):,} full-history versus past-only replays passed, covering every snapshot.
- {passed} unit tests passed, including future revisions, receipt/inference timing, missingness, multi-issuer abstention, altered numeric meanings, and exact evidence spans.

| Stock | Tagged articles | Single-ticker headlines | Usable stock-week observations |
|---|---:|---:|---:|
{chr(10).join(per_symbol)}

Tagged article counts overlap across stocks. The API is one Benzinga distribution
family, not thousands of independent sources. Completion means pagination finished;
it does not certify all historical reporting. The rejected rows make analytical
coverage incomplete, and are retained in the quarantine ledger.

## Web agents to structured signals

The research agent located four primary issuer announcements. Original pages
were captured and hashed; exact evidence spans were checked against the captured
text. A bounded schema produced event categories, direct issuer relevance and
positive/negative/mixed/unknown labels. The numeric current-evidence features are
saved in `web-agent/features.json`.

{links}

These are selective company announcements, not a representative media sample.
For Apple, an operational milestone did not establish a financial improvement,
so its numeric financial-direction label is missing. The other positive labels
are uncalibrated descriptions, not expected returns. Buyback authorization is not
completed buying, and reported growth is not an analyst-consensus surprise.

Current web pages are **observed-only** and cannot enter this historical test.
They retain publication-day precision and actual receipt times. Counts describe
collected evidence, not events newly occurring today. Immediate research-demo
features use zero additional latency, with an actual current cutoff.

## Limits and next test

The 12 names were selected now for industry diversity and are not a survivor-free
universe. Historical news is the provider's currently retained version, with no
complete original revision archive. Model training contamination is not excluded.
Prices reuse the earlier research panel and its documented identity/adjustment
limitations. The two historical years have already been examined in this project.
The windows overlap in some holiday weeks. Missing news is not neutral sentiment.

The implementation collapses exact normalized headline repetitions within 24 hours;
semantic syndication/event resolution is not solved. Code review replaced an
unordered-token heuristic that could merge changed numerical meaning. Original
results/code are retained in `initial-diagnostic`; this correctness fix left the
reported correlations unchanged; one NVDA stock-week tone/count changed. No universe, horizon or classifier tuning followed
inspection of the result.

The next useful hypothesis is event-specific: guidance changes, financing, or
regulatory developments combined with insider activity and financial quality.
First validate extraction on a representative labeled sample and complete the
issuer/filing and terminal-price foundation. Then freeze insider-only,
insider+quality, insider+news and combined variants under identical risk controls.
This wider combined experiment is not implemented or validated by this pilot.

This deliverable is a callable offline research pipeline and report. No new app
panel, recurring crawler, paper order, live order or existing frozen study was
enabled or changed.

## Sources and reproduction

[Alpaca archive](https://docs.alpaca.markets/us/docs/historical-news-data),
[pagination and updated-date semantics](https://docs.alpaca.markets/us/reference/news-3),
[FinBERT](https://huggingface.co/ProsusAI/finbert).

See `docs/NEWS_SIGNAL_RESEARCH.md` for commands and contracts. Source/input hashes,
protocol, diagnostic lock, raw pages, classifier outputs, all feature snapshots,
web evidence, unit-test XML and original reviewed results are retained here.
"""
    (root / "report.md").write_text(report)
    code = root / "code"
    code.mkdir(exist_ok=True)
    files = [*lock["code_sha256"], "scripts/research/report_news_signals.py",
             "tests/research/test_news_capture.py", "tests/research/test_news_signals.py", "docs/NEWS_SIGNAL_RESEARCH.md"]
    for name in files:
        shutil.copyfile(name, code / Path(name).name)
    manifest = {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*"))
                if p.is_file() and p.name != "manifest.json"}
    (root / "manifest.json").write_text(json.dumps({"files": manifest}, indent=2))
    for name, expected in manifest.items():
        if sha(root / name) != expected:
            raise ValueError("Artifact integrity failure")
    print(json.dumps({"report": str(root / "report.md"), "verified_files": len(manifest), "passed_tests": passed,
                      "causal_replays": len(result["causal_replays"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    main(parser.parse_args().root)
