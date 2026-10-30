# Five-year stock-ranking expansion

This experiment extends the September 7 small-basket study into two requested universes: a reproducible 100-stock basket spread across all 11 sectors, and the complete September 4, 2026 S&P 500 roster (503 securities representing 500 companies). The 100-stock basket is a subset of that roster, balanced by sector rather than by market capitalization.

The evaluation spans September 7, 2021 through September 4, 2026, both opening prices. Ridge, shallow boosted trees, momentum, eligible-universe equal weight and SPY buy-and-hold use the same dates and declared costs. The initial ranking signal is September 3, 2021; the Labor Day closure makes September 7 the next session. Models train on earlier data and only matured historical outcomes, then select the top third and rebalance every 21 sessions. The final shortened holding is liquidated at the fixed endpoint.

[Full results, diagnostics and chart](../.research-artifacts/prediction-wide-2026-09-07/report.md) live beside the immutable source responses, frozen choices, numerical panels, predictions, outcomes, portfolio ledgers and independent verification receipts.

This is a **current-roster historical diagnostic**, not a point-in-time S&P membership backtest. Historical member changes were captured and checked against selected primary announcements, but removed securities, issuer lineage and terminal distributions are not yet qualified. Current sectors and surviving members retain hindsight bias. Raw provider prices are revised and corporate-action adjusted; exact arithmetic verification does not certify their economic interpretation.

Source capture retained 1,298,499 bars. DOW returned no data under the declared as-of request. Alternative as-of queries returned history predating the current Dow security's 2019 separation, so those prices were preserved for review instead of silently substituted. Zero-volume source bars have no executable normalized open. Missing intraperiod valuations are omitted and explicitly recorded without inventing a price; any missing required trading or final price blocks exact P&L.

A separately declared data-quality sensitivity preserves the initial results and excludes training windows around three issuer-confirmed structural discontinuities: APTV December 5, 2017; EQT November 13, 2018; RTX April 3, 2020. Evaluation prices, membership, model parameters and portfolio rules remain unchanged. Quarantining a window does not reconstruct the missing corporate-action returns or qualify all other data.

Entry points:

- `scripts/research/capture_prediction_wide.py --root ROOT`: checkpointed authenticated GET capture, using existing configured Alpaca credentials.
- `scripts/research/prediction_wide_ranking.py --panel PANEL --output NEW_DIRECTORY`: offline chronological prediction, with missing-history eligibility and explicit missing training labels.
- `scripts/research/prediction_wide_portfolios.py --panel PANEL --predictions PREDICTIONS --output NEW_DIRECTORY`: offline costed comparison.
- `scripts/research/prepare_prediction_quality.py --root ROOT`: preserves the separately frozen training-data quarantine.
- `scripts/research/report_prediction_wide.py --root ROOT`: renders saved results.

The approved paper-trial schedule and its earlier frozen research criteria are unchanged. These experiments place no orders.
