# Historical disclosure purchase research

**Follow-up status:** the fixed insider + financial quality + risk-controls
hypothesis was tested, failed, and was retired with user approval on September 7,
2026. See [final test and retirement](INSIDER_QUALITY_FINAL_TEST.md). The earlier
pilot below remains historical evidence, not an active recommendation to promote
or keep tuning that strategy.

The September 7 experiment is in
`.research-artifacts/disclosure-signals-2026-09-07/report.md`.
It tests a Senate electronic-disclosure archive and a separately labeled
corporate-insider archive proxy. It submits no orders and changes no frozen
forward-study or paper-trial configuration.

Signals become usable only after their public filing/disclosure date. The
strategy rebalances at the first session opening each week, ranks the prior
90 calendar days of disclosed purchase dollars, and assigns 10% to each of
at most ten stocks. Unused slots remain cash. Historical S&P membership is
checked at the preceding close. Additional five-session delay and doubled
transaction costs are declared sensitivities.

The original intended Form4-only and all-Congress experiments are not yet
fully qualified. The insider archive lacks original/amended document type
and accessions; the Senate archive excludes the House and scanned reports.
The report preserves these limits and the original missing-DOW failures.
A separate DOW valuation sensitivity fills only observed post-separation
prices, without changing any selection or original price artifact.

## Reproduce from the saved artifacts

Run in the TradingAgents checkout. Do not run `prepare` over the frozen root.

```sh
PYTHONPATH=. .venv/bin/python scripts/research/verify_disclosure_signals.py --root .research-artifacts/disclosure-signals-2026-09-07
PYTHONPATH=. OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 .venv-prediction-lab/bin/python scripts/research/disclosure_signals.py score --root .research-artifacts/disclosure-signals-2026-09-07
PYTHONPATH=. OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 .venv-prediction-lab/bin/python scripts/research/repair_disclosure_valuation.py score --root .research-artifacts/disclosure-signals-2026-09-07
PYTHONPATH=. .venv-prediction-lab/bin/python scripts/research/report_disclosure_signals.py --root .research-artifacts/disclosure-signals-2026-09-07
PYTHONPATH=. .venv-prediction-lab/bin/python -m pytest tests/research/test_disclosure_signals.py tests/research/test_prediction_event_accounting.py -q
```

Preparation uses `.venv` for Arrow ingestion; scoring uses the existing
numerical research environment. No environment or frozen dependency was
modified. Hash manifests, declared rules, normalized signals, all weekly
selections, both cost levels, delay sensitivities and every original failure
are retained. The extra return of a riskier portfolio is not a demonstrated
risk-adjusted advantage over SPY.
