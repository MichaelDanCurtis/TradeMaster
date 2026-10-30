"""Report every frozen disclosure strategy, sensitivity and known evidence gap."""
import argparse
import csv
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys

import numpy as np
from scripts.research.disclosure_signals import sha, write


def pct(value):
    return 'Unavailable' if value is None else f'{value*100:.2f}%'


def run(root):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    original = json.loads((root/'results.json').read_text())
    results = json.loads((root/'dow-valuation/results.json').read_text())
    verification = json.loads((root/'verification.json').read_text())
    lines = ['# Historical disclosure purchase signals', '',
             '**The Senate pilot underperformed SPY. The provisional corporate-insider pilot earned more than SPY, with substantially greater volatility and drawdown. Neither is a validated trading edge.**', '',
             'These are two separately defined historical purchase-signal strategies, not a reproduction of Quiver Quantitative or Finbold returns. No language model chooses the trades. Rules were written before the new outcomes: weekly first-session open, sum purchase dollars disclosed during the prior 90 calendar days, ten largest totals, 10% per name, unused slots cash. Date-only filings cannot be used until the following trading session. No leverage; cash earns zero.', '',
             'Universe: the existing dated historical S&P membership reconstruction at the preceding close. Exact ticker matching only; membership, source symbol histories and corporate actions remain unqualified. This is not an all-US-stock test. Both stock and SPY portfolios pay the declared 11 basis points per traded side, including final liquidation. Prices are adjusted daily opens; fractions are allowed. Taxes and actual broker execution are not modeled.', '',
             '## Main comparisons', '',
             '| Test | Dates, first open to final open | Strategy annualized | SPY annualized | Strategy worst drawdown | SPY worst drawdown |',
             '|---|---|---:|---:|---:|---:|']
    groups = [('senate-2019-2020', 'Senate electronic-disclosure pilot'), ('insider-proxy-2019-2025', 'Corporate-insider archive proxy')]
    rows = []
    for key, label in groups:
        a, b = results[key]['delay0-cost11'], results[key]['SPY-cost11']
        lines.append(f"| {label} | {a['first_date']}–{a['last_date']} | {pct(a['cagr'])} | {pct(b['cagr'])} | {pct(a['max_drawdown'])} | {pct(b['max_drawdown'])} |")
    lines += ['', 'These are different date ranges; each strategy must be compared with its own same-period SPY control. The two strategy CAGRs are not a head-to-head ranking.', '',
              '## Risk and execution sensitivity', '',
              '| Test | Annual volatility: strategy / SPY | Sharpe, zero cash rate: strategy / SPY | Double-cost CAGR: strategy / SPY | Five extra sessions delay CAGR |',
              '|---|---:|---:|---:|---:|']
    for key, label in groups:
        a, b = results[key]['delay0-cost11'], results[key]['SPY-cost11']
        lines.append(f"| {label} | {pct(a['annualized_volatility'])} / {pct(b['annualized_volatility'])} | {a['sharpe_zero_rate']:.2f} / {b['sharpe_zero_rate']:.2f} | {pct(results[key]['delay0-cost22']['cagr'])} / {pct(results[key]['SPY-cost22']['cagr'])} | {pct(results[key]['delay5-cost11']['cagr'])} |")
    lines += ['', 'A larger raw return alongside a deeper drawdown and higher volatility is not evidence of a risk-matched advantage. The delayed and doubled-cost versions were declared before scoring, not selected after seeing their performance. The zero-rate Sharpe assumes no cash yield; it is not a Treasury-excess Sharpe.', '',
              '![Observed historical account-value diagnostics](comparison.png)', '',
              '## Independent yearly starts', '',
              'Each row starts a fresh unit-capital portfolio at the first session of the year and liquidates at the first session of the next year. These are total returns, not annualized figures. They share the same data and rules and are not independent untouched holdouts. They do not stitch exactly into the continuous portfolio, because restarting changes holdings and costs.', '',
              '| Year | Senate | Insider proxy | SPY |', '|---|---:|---:|---:|']
    for year in range(2019, 2026):
        ins = results[f'insider-proxy-{year}']; sen = results.get(f'senate-{year}')
        lines.append(f"| {year} | {pct(sen['delay0-cost11']['net_return']) if sen else 'Outside archive test'} | {pct(ins['delay0-cost11']['net_return'])} | {pct(ins['SPY-cost11']['net_return'])} |")
    lines += ['', '## Coverage and qualifications', '',
              '- **Senate:** 2,715 normalized stock-purchase rows across the archive, with original PTR links and a received/disclosure date. The archive ends March 10, 2021, so the two full target years are 2019–2020. This excludes House members and has known scanned-PDF gaps. It cannot establish how an all-Congress strategy would perform.',
              '- **Insider proxy:** the 5,648,171-row OpenSECFinancials archive yields 169,280 positive non-derivative common/ordinary-stock purchase records by directors/officers across its history. Code PURCHASE includes open-market and private purchases. Grants, sales, exercises, preferred shares, derivatives, invalid dates and missing prices in disclosure records are excluded. All those counts precede membership and test-period filtering.',
              '- **Original Form 4-only test remains unqualified:** direct SEC quarterly ZIP download returned HTTP403. The alternate archive lacks accession numbers, issuer CIK and original/amended document type. It cannot reliably enforce the originally intended original-Form4-only rule. This is why its results are explicitly named insider_proxy. It is not promoted to the original hypothesis.',
              f"- **Cross-check:** {verification['cross_archive_matches']:,} of {verification['selected_insider_signal_count']:,} insider records used by the frozen selections match ticker, insider CIK, transaction date, shares and price in a separate SEC-derived archive that retains accessions. This corroborates fields, not complete publication timing or independent data provenance. The unmatched records remain identified; no favorable subset was rescored.",
              '- **DOW valuation sensitivity:** the original price panel had no Dow observations, blocking several runs. Two previously captured alternate-asof requests agree. A separate valuation version uses only their observed positive-volume bars from April2,2019, when the new Dow began regular-way trading. It preserves all frozen selections, all other prices and every original incomplete result. The provider mapping discrepancy remains unresolved; this is a provisional source sensitivity, not automatic data admission.',
              '- **Survivorship and identity:** dated membership improves on using today\'s constituents, but both disclosure archives can have incomplete or renamed-symbol histories. The model never silently substitutes symbols. Missing or unmatched disclosures reduce coverage and may bias selection; an apparently complete equity curve does not resolve that.',
              '- **Accounting:** both main corrected runs have daily observed price coverage. Existing documented merger conversions are reused if held; merger cash is recognized at conversion and assumed usable at the next weekly rebalance. Settlement delays, fractional-share cash-in-lieu, full delisting entitlement coverage and complete adjustment provenance remain unverified.', '',
              '### Disclosure coverage in the target input window', '',
              'October1,2018–December31,2025; Senate naturally ends earlier. Exact-symbol tests at the disclosure date, before any price-outcome scoring:', '',
              '| Source | Member at disclosure | Not a member at disclosure | Outside captured historical union |', '|---|---:|---:|---:|']
    for source, counts in verification['source_coverage'].items():
        lines.append(f"| {source} | {counts.get('member_at_disclosure', 0):,} | {counts.get('not_member_at_disclosure', 0):,} | {counts.get('outside_historical_union', 0):,} |")
    primary_path = root/'sources/sec-verification/assessment.json'
    if primary_path.exists():
        primary = json.loads(primary_path.read_text())['results']; confirmed = sum(x.get('date_matches') is True for x in primary)
        lines += ['', f'An additional deterministic sample of {len(primary)} matched insider signals was checked against official SEC submissions metadata: {confirmed} filing dates matched. See `sources/sec-verification/assessment.json`; this sample does not certify the other records.']
        amended = [x['symbol'] for x in primary if any(v.get('form') == '4/A' for v in x.get('official', {}).values())]
        if amended:
            lines += ['', 'The official sample also found an amendment ambiguity for '+', '.join(amended)+': the same transaction fields match both an original Form4 and a Form4/A. This is direct evidence that transaction-field matching alone cannot qualify original-only data. No result was silently filtered or reoptimized after this check.']
    lines += ['', '## Every declared sensitivity', '', '| Test | Variant | State | Annualized return | Worst drawdown | Two-sided turnover sum |', '|---|---|---|---:|---:|---:|']
    for label, variants in results.items():
        for variant, a in variants.items():
            lines.append(f"| {label} | {variant} | {a['state']} | {pct(a.get('cagr'))} | {pct(a.get('max_drawdown'))} | {a.get('two_sided_turnover_sum', 0):.2f} |")
            rows.append({'test': label, 'variant': variant, **{k: a.get(k) for k in ['state', 'first_date', 'last_date', 'net_return', 'cagr', 'max_drawdown', 'annualized_volatility', 'sharpe_zero_rate', 'two_sided_turnover_sum']}})
    lines += ['', '## Verification', '',
              f"- {len(verification['causal_replays'])} first/middle/last selections reproduced after physically removing all future disclosures and future calendar entries.",
              '- All 22 target-file hashes and original source-panel hashes verified. Every target has at most ten names, no leverage, and an explicit residual cash weight.',
              '- 23 focused tests passed for date timing, five-session delay, future-disclosure invariance, HTML ticker parsing, instrument filtering, duplicate handling and existing merger accounting.',
              '- 66 original and 44 DOW-sensitivity results were replayed with separate transaction-cost solvers; these share the same corporate-action implementation. SPY controls remain unchanged.',
              '- The DOW-only price change was verified; no pre-inception prices were admitted. Original incomplete calculations remain in `results.json`; the explicitly revised valuation results are in `dow-valuation/results.json`.', '',
              '## Decision', '',
              '**Senate pilot: reject this rule as evidence of an improvement over SPY. Insider proxy: continue data qualification and risk analysis, with no strategy deployment.** The next useful step is an original-filing-backed corpus with amendment and security identity checks, followed by the same frozen rules. Full House/Senate coverage is needed before describing the congressional test as complete. Do not tune the 90-day lookback or choose the five-day delay because of these outcomes.', '',
              '## Sources', '',
              '- [SEC bulk insider datasets and scope](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets)',
              '- [Senate Stock Watcher archive and scanned-report limitations](https://github.com/timothycarambat/senate-stock-watcher-data)',
              '- [OpenSECFinancials, published by SpongeBob126; CC BY4.0 attribution](https://huggingface.co/datasets/SpongeBob126/OpenSECFinancials)',
              '- [SarthakVishnu SEC-derived transaction cross-check documentation](https://huggingface.co/datasets/SarthakVishnu/dissertation-dataset/blob/main/data_collection_readme.md)',
              '- [Dow separation and regular-way trading start](https://investors.dow.com/en/news/news-details/2019/Dow-completes-separation-from-DowDuPont/default.aspx)', '']
    (root/'report.md').write_text('\n'.join(lines))
    with (root/'summary.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), constrained_layout=True)
    for ax, (key, label) in zip(axes, groups):
        for variant, legend, color in [('delay0-cost11', label, '#156c91'), ('SPY-cost11', 'SPY buy and hold', '#cf7b23')]:
            curve = results[key][variant]['curve']; x = np.array([r['date'] for r in curve], dtype='datetime64[D]'); y = [100*r['equity'] for r in curve]
            ax.plot(x, y, label=legend, color=color, linewidth=1.7)
        ax.set_title(label); ax.set_ylabel('Value, initial capital = 100'); ax.grid(alpha=.2); ax.legend(loc='upper left')
    fig.suptitle('Disclosure purchase signals: provisional archive research\n11bps per traded side; same frozen selections with DOW valuation sensitivity', fontsize=13)
    fig.savefig(root/'comparison.png', dpi=150); fig.savefig(root/'comparison.svg'); plt.close(fig)
    dependencies = [Path('scripts/research')/name for name in ['disclosure_signals.py', 'repair_disclosure_valuation.py', 'verify_disclosure_signals.py', 'report_disclosure_signals.py', 'prediction_event_accounting.py', 'prediction_portfolios.py', 'verify_prediction_wide.py', 'evaluate_astra_capsules.py']]
    for path in dependencies:
        shutil.copy2(path, root/'code'/path.name)
    shutil.copy2('tests/research/test_disclosure_signals.py', root/'code/test_disclosure_signals.py')
    write(root/'code/receipt.json', {'source_files': {str(p): sha(p) for p in dependencies}, 'python': sys.version,
                                   'packages': {name: importlib.metadata.version(name) for name in ['numpy', 'scipy', 'matplotlib', 'pytest']}})
    files = [p for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json']
    write(root/'manifest.json', {'created_at': datetime.now(timezone.utc).isoformat(), 'files': {str(p.relative_to(root)): sha(p) for p in sorted(files)}})
    print(root/'report.md')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--root', type=Path, required=True)
    run(parser.parse_args().root)
