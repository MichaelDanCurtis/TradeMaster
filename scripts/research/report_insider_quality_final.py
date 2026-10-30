"""Preserve and present the final fixed-hypothesis test, including failures."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import numpy as np

from scripts.research.insider_quality_final import verify_lock, load_inputs
from scripts.research.disclosure_signals import sha


LABELS = {"original_insider": "Original insider portfolio",
          "risk_insider": "Insider + diversification/risk controls",
          "risk_insider_coverage_matched": "Insider, financial coverage matched + controls",
          "risk_insider_quality": "Insider + quality + controls",
          "SPY_buy_hold": "SPY buy and hold", "SPY_risk12": "SPY with 12% volatility target"}


def report(root):
    verify_lock(root)
    protocol, panel, _ = load_inputs(root)
    result = json.loads((root / "results.json").read_text())
    verification = json.loads((root / "causal-verification.json").read_text())
    lock_sha = sha(root / "targets-lock.json")
    if result["targets_lock_sha256"] != lock_sha or verification["targets_lock_sha256"] != lock_sha:
        raise ValueError("Output belongs to a different frozen experiment")
    tests = list(ET.parse(root / "unit-tests.xml").getroot().iter("testsuite"))
    if any(int(s.attrib.get(k, 0)) for s in tests for k in ["failures", "errors", "skipped"]):
        raise ValueError("Test report is not all passing")
    test_count = sum(int(s.attrib["tests"]) for s in tests)
    portfolios = result["portfolios"]
    tables = []
    for cost in ["11", "22"]:
        rows = []
        for variant in protocol["variants"]:
            x = portfolios[variant][cost]
            if x["state"] != "complete" or x["valuation_gaps"]:
                rows.append(f"| {LABELS[variant]} | Incomplete | — | — | — |")
                continue
            rows.append(f"| {LABELS[variant]} | {100*x['cagr']:.2f}% | {100*x['max_drawdown']:.2f}% | {100*x['annualized_volatility']:.2f}% | {x['sharpe_zero_rate']:.2f} |")
        tables.append(f"### {cost} basis points per traded side\n\n| Portfolio | Annualized return | Worst drawdown | Realized annual volatility | Sharpe (zero cash rate) |\n|---|---:|---:|---:|---:|\n" + "\n".join(rows))
    q = portfolios["risk_insider_quality"]["11"]
    baseline = portfolios["risk_insider_coverage_matched"]["11"]
    spy = portfolios["SPY_risk12"]["11"]
    periods = []
    for key in ["2019-2021", "2022-2023", "2024-2025"]:
        periods.append(f"| {key} | {100*q['period_returns'][key]:.2f}% | {100*baseline['period_returns'][key]:.2f}% | {100*spy['period_returns'][key]:.2f}% |")
    coverage = json.loads((root / "SEC-coverage.json").read_text())
    decisions = json.loads((root / "decision-evidence.json").read_text())
    gate_rows = []
    for cost, item in result["verdict"].items():
        for gate, passed in item["gates"].items():
            gate_rows.append(f"| {cost} | {gate} | {'Pass' if passed else 'Fail'} |")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    for variant, color, style in [("risk_insider_quality", "#087e8b", "-"),
                                   ("SPY_risk12", "#bf5600", "-"),
                                   ("risk_insider_coverage_matched", "#777777", ":"),
                                   ("SPY_buy_hold", "#6b53a3", "--")]:
        x = portfolios[variant]["11"]
        times = [datetime.fromisoformat(row["date"]) for row in x["curve"]]
        equity = np.array([row["equity"] for row in x["curve"]])
        axes[0].plot(times, equity*100000, label=LABELS[variant], color=color, linestyle=style, linewidth=1.5)
        peaks = np.maximum.accumulate(np.r_[1., equity])[1:]
        axes[1].plot(times, 100*(equity/peaks-1), color=color, linestyle=style, linewidth=1.3)
    axes[0].set_title("Final insider + quality test: failed the frozen performance gate")
    axes[0].set_ylabel("Value of $100,000 (USD)")
    axes[0].legend(fontsize=8, loc="upper left")
    axes[1].set_ylabel("Drawdown (%)")
    for ax in axes:
        ax.grid(alpha=.2)
    fig.text(.07, .01, "2019-01-02 to 2026-01-02 • 11 bps per side • retrospective archive limitations apply • no orders", fontsize=8)
    fig.tight_layout(rect=[0, .025, 1, 1])
    fig.savefig(root / "comparison.png", dpi=160)
    fig.savefig(root / "comparison.svg")
    plt.close(fig)
    text = f"""# Final insider + quality test: failed

**This fixed strategy did not beat the simpler comparison.** From the January 2,
2019 opening to the January 2, 2026 opening, insider activity plus financial
quality and risk controls returned **{100*q['cagr']:.2f}% annually**, versus
**{100*spy['cagr']:.2f}%** for SPY using the same 12% trailing volatility target.
Its drawdown was deeper ({100*abs(q['max_drawdown']):.2f}% versus
{100*abs(spy['max_drawdown']):.2f}%). It failed the predeclared performance gates
at both transaction-cost levels. No parameters were retuned.

The appropriate conclusion is to stop pursuing this particular stock-selection
hypothesis as a demonstrated advantage. This does not establish that all active
investing is impossible; it establishes that this version did not earn its extra
complexity in this retrospective test.

![Portfolio value and drawdowns](comparison.png)

## Complete comparisons

{chr(10).join(tables)}

The 12% target is based only on trailing estimates; realized volatility differs.
SPY is already a diversified fund, so the single-stock and sector limits apply
to direct stock portfolios, not to the fund wrapper. The original insider
portfolio retains its old ten-name rules as a reference; it is not the controlled
comparison. Its larger nominal return came with substantially larger risk.

## What quality actually added

Against the insider baseline using exactly the same available financial coverage,
the quality filter added **{100*(q['cagr']-baseline['cagr']):.2f} percentage points
of annual return**, reduced drawdown by
**{100*(q['max_drawdown']-baseline['max_drawdown']):.2f} percentage points**, and
changed Sharpe from {baseline['sharpe_zero_rate']:.2f} to {q['sharpe_zero_rate']:.2f}.
That modest improvement did not surpass risk-controlled SPY.

The much larger difference between the all-covered insider portfolio and the
financial-coverage-matched portfolio comes from changing data coverage/eligible
companies. It cannot be credited to the quality rule, and can reflect survivor
or issuer-mapping selection. The matched control prevents hiding that distinction.

### Calendar-period total returns, 11 bps per side

| Period | Insider + quality + controls | Coverage-matched insider control | Risk-controlled SPY |
|---|---:|---:|---:|
{chr(10).join(periods)}

These are mark-to-market changes through the final observed opening in each
calendar period, including fees incurred within that period. They do not reset
holdings, are not annualized, and exclude the final January 2, 2026 liquidation
from the 2024–2025 calendar segment. Full-run CAGR includes final liquidation.
The subperiods have previously been available to this project; none is an untouched
holdout. The middle period was better for quality, but the full and late-period
tests did not pass.

## Frozen rules

- Weekly first-session opening, using insider disclosures from the prior 90
  calendar days, historical membership at the preceding close and deterministic
  purchase-dollar ranking. No future prices enter selection.
- Positive annual net income, operating cash flow and free cash flow required.
  The four required facts use the same accession/filing and matching annual period;
  assets are from that period end. Filing date must precede the previous session
  date; stale, conflicting, missing or unsupported observations remain unknown.
- At most 20 stocks; 5% target capital per stock and four names per static sector
  bucket. Unknown sectors share one bucket. Unfilled slots remain cash.
- Scale weights down using 63 aligned daily returns through the previous close
  toward 12% annual volatility, with no leverage or upward rescaling. Limits apply
  at weekly rebalances; holdings can drift between them.
- Cash earns zero; 11 and 22 bps costs apply to each side of turnover and final
  liquidation. Taxes, financing and execution receipts are not modeled.

## Predeclared acceptance checks

At both cost levels, quality had to exceed the matched insider baseline and
risk-controlled SPY in CAGR, exceed both in Sharpe by at least 0.10, stay within
two percentage points of risk-controlled SPY's worst drawdown, and exceed its
2024–2025 calendar-period return. Completing a backtest alone is not a pass.

| Cost (bps) | Gate | Result |
|---|---|---|
{chr(10).join(gate_rows)}

## Evidence and limitations

- {len(coverage)} archived signal tickers considered for SEC capture;
  {sum(r['state']=='captured' for r in coverage)} had numeric issuer mappings and verified archived SEC files.
- {len(decisions)} weekly decisions frozen before valuation; all
  {verification['portfolio_replays']:,} controlled portfolio decisions replayed
  identically with future disclosures and financial facts removed.
- {test_count} tests passed. All {result['two_cost_solver_replays']} portfolio/cost
  runs agreed between two cost solvers sharing the existing corporate-action engine.
- All six portfolios completed at both costs with no held-price valuation gaps.
  This proves accounting completion, not complete historical data coverage.
- Insider signals remain the earlier SEC-derived archive proxy: original/amended
  filing identity and complete historical issuer identity are unqualified.
- SEC facts retain filing dates but were retrieved today. Retrospective issuer
  and sector mappings, incomplete coverage and possible survivor selection remain.
  Matching coverage does not remove these limits versus the whole-market benchmark.
- Existing adjusted-price, merger-entitlement and DOW valuation qualifications
  remain. Corporate-action cash is credited at conversion and assumed available
  for the next rebalance; this is research accounting, not settlement evidence.
- The existing forward study's {verification['forward_study_dependencies_unchanged']}
  dependency hashes are unchanged. No orders, schedules, model fitting or live
  settings were changed.

Reproduction: see `docs/INSIDER_QUALITY_FINAL_TEST.md`. The saved protocol, target
lock, filing evidence, complete decisions, costed curves and ledgers, original
source hashes, test results, code snapshots and manifest allow review.

Primary source context: [SEC financial-data API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and [SEC insider-data limitations](https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets).
"""
    (root / "report.md").write_text(text)
    code = root / "code"
    code.mkdir(exist_ok=True)
    lock = json.loads((root / "targets-lock.json").read_text())
    files = list(lock["code_sha256"]) + [__file__, "scripts/research/verify_insider_quality_final.py",
             "tests/research/test_insider_quality_final.py", "docs/INSIDER_QUALITY_FINAL_TEST.md"]
    for name in files:
        shutil.copyfile(name, code / Path(name).name)
    manifest = {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob("*")) if p.is_file() and p.name != "manifest.json"}
    (root / "manifest.json").write_text(json.dumps({"files": manifest}, indent=2))
    for name, expected in manifest.items():
        if sha(root / name) != expected:
            raise ValueError("Artifact verification failed")
    print(json.dumps({"report": str(root / "report.md"), "overall_pass": result["overall_pass"],
                      "files_verified": len(manifest), "tests": test_count}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    report(parser.parse_args().root)
