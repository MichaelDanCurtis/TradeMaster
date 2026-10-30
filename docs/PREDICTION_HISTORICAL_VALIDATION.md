# Additional historical validation

Results and all qualifications are in `.research-artifacts/prediction-historical-validation-2026-09-07/report.md`. The completed additional interval is March 4, 2019–September 3, 2021. The historical-membership portfolio resolves its interval endpoints after explicit merger-entitlement accounting, but retains one missing BIIB daily open and broader security-master limitations.

The buffer improved historical-membership CAGR from 20.04% to 20.86%, below SPY at 22.84%, with a deeper observed drawdown than SPY. Current-roster cohorts perform better but remain survivor-selected. A separately recorded EXE security-inception correction materially changed the current-cohort forecasts and reversed the 100-stock buffer advantage. Do not present the original 26.22% / 27.51% 100-stock result as the corrected result; the corrected numbers are 32.58% / 30.20%.

## Research tools

- `validate_prediction_history.py prepare|predict|score --root NEW_ROOT` declares the earlier interval, fits unchanged HGB, freezes baseline/buffer targets, and runs the original accounting. Source locations and dates are explicitly declared in its protocol. Use a new root; completed files cannot be overwritten.
- `reconcile_prediction_history.py --root ROOT` uses the archived event terms, prices and source documents to prepare separate valuation panels and score the same frozen selections. It requires the captured event inputs retained in the reference run; it does not fetch them implicitly.
- `prediction_event_accounting.py` processes merger cash and adjusted-unit successor entitlements. It charges no synthetic sale fee on cash consideration. Same-open events use opening holdings, avoiding double distributions to newly delivered shares.
- `prediction_identity_sensitivity.py --root ROOT` creates a separate current-security correction for EXE before February 10, 2021. It preserves all other input observations and freezes newly fitted forecasts before scoring.
- `report_prediction_history.py --root ROOT` combines the results, source citations, incomplete runs, risk qualifications, charts and file manifest.

Use `PYTHONPATH=.` and `.venv-prediction-lab/bin/python`, with `OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4` for numerical stages. The capture scripts archived in the run's `code/` use `.venv/bin/python` and the configured read-only provider.

Validation: 38 focused tests; 15 first/middle/last future-removal model refits; target/source hash checks; no-event accounting parity; and two transaction-cost solvers for the corporate-action runs. The two cost solvers share the tested event-processing logic and should not be described as two independent implementations of every corporate action.

## Remaining requirements

The 2021–2026 historical-membership run still stops at SBNY/SIVB on April 10, 2023. Requests for SBNY, SIVBQ, FRCB and CHKAQ historical OTC bars returned HTTP 403. Completing the affected historical portfolios requires authorized OTC observations and remaining security/corporate-action reconciliation. Do not invent a zero recovery, a sale at the last listed price, or a conversion of cancelled equity into newly issued shares.

The fixed forward study has not been modified by this historical validation. Its existing data conventions should not be conflated with the separately corrected current-security sensitivity run. This work establishes neither live broker performance nor a reliable advantage over SPY.
