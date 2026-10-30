# Historical prediction laboratory

The September 7, 2026 experiment tests relative stock ranking and variance forecasts after the general time-series models failed to improve the earlier price-path benchmark. It is a new declared research objective; it does not change the earlier benchmark scores or qualify the existing paper strategy.

Results and chart: [complete experiment report](../.research-artifacts/prediction-lab-2026-09-07/report.md). Raw responses, frozen protocol, price panel, predictions, realized outcomes, fees, portfolio ledgers, source hashes, independent verification and pinned Python dependencies are in that artifact directory.

The fixed basket contains 33 surviving stocks across 11 sectors plus a separate SPY benchmark. Historical daily bars cover January 2016 through September 4, 2026; evaluation begins January 2023. Ranking candidates are skipped-month momentum, Ridge and shallow boosted trees. Reversal candidates use the past five days with and without subtracting an estimated market component. Variance candidates are trailing-20, EWMA and GARCH(1,1). No parameter searches were performed.

Ridge and boosted-tree rankings beat the matched basket and SPY cumulatively under both cost scenarios in this retrospective experiment. Reversal failed to beat the basket after base costs. GARCH improved 20-day variance QLIKE and reduced mean squared error by about 18%; this is a risk forecast finding, not a profit forecast. See the report for dates, drawdowns, annual slices, uncertainty and all controls.

This remains exploratory: the current-survivor universe is selected with hindsight, adjusted bars are revised, and adjusted opens are total-return proxies rather than historical executable quotes. Positive results require an independent universe/regime check before a frozen paper candidate. No execution settings or approvals were changed.

To reproduce using the captured panel, use `.venv-prediction-lab/bin/python` and the recorded `requirements.txt`. Forecast scripts accept `--panel PATH --output NEW_DIRECTORY` and refuse existing output directories:

- `scripts/research/prediction_ranking.py`
- `scripts/research/prediction_reversal.py`
- `scripts/research/prediction_risk.py`

`prediction_portfolios.py --root EXPERIMENT_DIRECTORY --output NEW_DIRECTORY` reads `ranking/predictions.json`, `reversal/predictions.json`, `panel.json` and `protocol.json`. `report_prediction_lab.py --root EXPERIMENT_DIRECTORY` regenerates the chart and report from saved results. Independent `verify_prediction_*.py` scripts document their own CLI arguments with `--help`.

The separate data capture script only performs authenticated GET requests using the already configured Alpaca provider and calendar. It writes a new protocol before fetching, retains exact raw response bytes and never sends an order. Offline forecasting scripts consume numerical files and require no brokerage credentials.

The next untested research direction from the agents is accession-dated SEC filing-change features. That requires its own frozen historical text capture and publication-time rules; it is not implemented in this experiment.
