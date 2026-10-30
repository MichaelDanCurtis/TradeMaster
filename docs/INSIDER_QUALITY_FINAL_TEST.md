# Final bounded insider and quality test

**Status: retired by user approval on September 7, 2026.** Further tuning and
deployment promotion of this fixed hypothesis are closed. Code and original
results are retained for audit and reproduction. Reopening requires a new
explicit user decision, rather than an automatic follow-on experiment.
See the [retirement record](research-decisions/insider-quality-final-retirement.json).

The September 7 run is saved at
`.research-artifacts/insider-quality-final-2026-09-07/report.md`.

The fixed hypothesis **failed**: positive annual earnings and free cash flow,
combined with diversified insider-purchase selection and trailing risk controls,
did not improve on SPY using the same volatility-targeting rule over 2019–2025.
The quality filter's incremental return over a coverage-matched insider baseline
was small. No further parameter search was performed.

## Frozen design

- January 2, 2019 opening through January 2, 2026 opening, including liquidation.
- Prior 90 calendar days of disclosed officer/director common-stock purchase
  dollars; date-only disclosure usable after its filing day; historical index
  membership from the prior close. Existing archive qualifications remain.
- Weekly next-open rebalancing, descending disclosed dollars and ticker tie-break.
- Quality requires positive net income, operating cash flow and free cash flow
  (operating cash flow less capital spending). Inputs come from a complete annual
  vintage with the same accession, reporting period and filing date, filed
  strictly before the preceding session date, with period end within 550 days.
- Four stocks per static sector bucket, at most 20 stocks and 5% each; unused
  slots remain cash. Unknown sectors share a single bucket.
- Scale weights down to a 12% estimated annual volatility target using 63 aligned
  daily returns through the preceding close. No leverage or upward rescaling of
  unused slots. Actual risk and weights can drift between weekly rebalances.
- Compare the original insider strategy, diversified/risk-controlled insider
  strategy, financial-coverage-matched insider control, quality strategy,
  buy-and-hold SPY, and SPY using the same volatility-targeting rule.
- Charge 11 and 22 basis points on each traded side, including liquidation.
  Cash earns zero and Sharpe uses a zero risk-free rate in every portfolio.

The primary gate required the quality strategy to exceed both the matched
insider control and risk-controlled SPY in CAGR and Sharpe (by at least 0.10),
have drawdown no more than two percentage points deeper than risk-controlled
SPY, and exceed risk-controlled SPY's 2024–2025 return, at both cost levels.
It failed all four performance gates at both cost levels.

## Reproduction and boundaries

`scripts/research/insider_quality_final.py prepare` freezes all selections before
`score` reads their outcomes. It refuses to replace existing frozen selections.
`scripts/research/verify_insider_quality_final.py` replays all weekly controlled
portfolios without future disclosures or financial statements. The valuation
uses two cost solvers and the existing shared explicit corporate-action engine.
Tests cover quality vintage alignment, future filing exclusion, missing data,
sector/name limits and covariance risk scaling.

```sh
.venv-prediction-lab/bin/python -m pytest \
  tests/research/test_insider_quality_final.py \
  tests/research/test_prediction_event_accounting.py \
  tests/research/test_disclosure_signals.py -q
```

For a fresh replay, copy the saved run, retaining protocol, locks, compiled
facts, decisions and target files. Remove only the copy's `results.json` and
`causal-verification.json`, then run:

```sh
.venv-prediction-lab/bin/python -m scripts.research.verify_insider_quality_final --root COPY_OF_RUN
.venv-prediction-lab/bin/python -m scripts.research.insider_quality_final score --root COPY_OF_RUN
```

The source paths and code hashes in the locks must still resolve and agree.
The report generator verifies them again and saves artifact hashes and source
code snapshots. The original forward study's 13 dependencies remain unchanged.

This is a retrospective, provisional economic test. The source insider archive
lacks original/amended filing identity. Historical issuer and sector mappings
are incomplete or retrospective; financial-data availability may favor surviving
mapped issuers. Current SEC archives preserve filing dates but are not certified
historical receipt vintages. The existing adjusted-price/merger/DOW qualifications
remain. No missing held prices were encountered in this run. These limits do not
justify asserting that all stock-selection methods are impossible, nor do they
justify deploying this unsuccessful particular method.

No orders, new schedules, live integrations, or changes to existing trials were
made. The conclusion is to close this fixed hypothesis, not add more features
or tune thresholds until these same historical years look profitable.
