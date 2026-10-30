# Frozen HGB improvement experiment

The experiment adds a stock-replacement buffer, portfolio risk constraints and SEC filing-dated financial features to the existing five-year HGB comparison. These are research tools; they do not change application strategy deployments or broker schedules.

The September 2026 run is in `.research-artifacts/prediction-improvements-2026-09-07/report.md`. It reports every prespecified variant. The S&P-roster buffer improved returns in this retrospective run; the same buffer hurt the 100-stock cohort. Fundamentals and the complete bundle did not improve returns. Current-roster survivorship bias and lack of genuinely unseen outcomes remain.

## Running a new experiment

Run from the TradingAgents repository with `PYTHONPATH=.`. Use a new artifact directory and keep all parameters fixed before observing results. The prior source is `.research-artifacts/prediction-wide-2026-09-07`.

1. Prepare the protocol with `scripts/research/prepare_prediction_improvements.py --source SOURCE --root NEW_ROOT`.
2. Run `scripts/research/capture_prediction_improvements.py MODE --root NEW_ROOT` for `sec`, `valuation`, and `historical`. The configured Alpaca account is used only for read-only market data. SEC needs no AI provider. Captures are rate limited and retain raw files and receipts.
3. Build the feature matrix using `build_prediction_fundamentals.py --root NEW_ROOT`, then the historical panel using `build_prediction_historical_panel.py --root NEW_ROOT`.
4. Run `run_prediction_improvements.py predict --root NEW_ROOT`, then `plan`, then `score` in that order. The `plan` stage hashes targets before scoring. Do not overwrite or performance-tune a completed run.
5. Run `verify_prediction_improvements.py --root NEW_ROOT`, then `report_prediction_improvements.py --root NEW_ROOT`. Use `.venv-prediction-lab/bin/python` with `OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4` for numerical stages; `.venv/bin/python` has the application/provider dependencies for capture.

The scorer independently replays transaction costs and reproduces the original HGB benchmark. Risk constraints apply at rebalance targets and may drift between monthly rebalances. Fundamentals preserve missing observations; companyfacts aggregates filtered by filing date do not guarantee complete original filing vintages or predecessor-CIK history.

## Historical membership qualification

The 745-security historical reconstruction retains former tickers. Missing outcomes never cause a stock to disappear from an already generated forecast. The run stops on unresolved held securities instead of fabricating sales, merger cash, stock conversions or zero writeoffs. Captured corporate actions still require security identity matching; a ticker can refer to different CUSIPs over time. See `historical/security-qualification.json` for the concrete remaining gaps. There is no complete survivorship-corrected five-year result yet.

## Prospective research runner

`forecast_prediction_improvements.py --panel NEW_PANEL --date YYYY-MM-DD --output NEW_DECISION` creates a fresh HGB and HGB-buffer decision without outcomes or broker orders. Supply `--previous PRIOR_DECISION` to carry prior planned holdings for the buffer. The panel must end on the decision session and explicitly include `closed_through` and timezone-aware `captured_at`; future sessions, reused historical dates and overwriting an existing decision are rejected. The runner conservatively waits until 16:15 New York time, including on early-close days.

This single-decision runner needs fresh data supplied by a capture process. The frozen forward comparison now has an active read-only capture and follow-up workflow, armed for the September 8 close; see [PREDICTION_FORWARD_STUDY.md](PREDICTION_FORWARD_STUDY.md). No forward observations have occurred yet. Preserve immutable inputs before each observation and resolve corporate-action accounting before reporting full portfolio performance. No broker receipts or future results are supplied by an offline forecast.
