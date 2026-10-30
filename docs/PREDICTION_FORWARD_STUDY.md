# Frozen forward comparison

The active research study is `.research-artifacts/prediction-forward-2026-09-07`. It compares the original price/volume HGB with the same model plus the fixed replacement buffer, and buy-and-hold SPY. It submits no orders. The existing Alpaca paper-order trial is a separate experiment.

A fresh 503-security S&P roster was captured on September 7, 2026. Provider asset IDs, names, active status, tradability, source responses, code hashes, model rules and the trading-session schedule are frozen in the protocol. This is a **fixed starting cohort**, not an index portfolio that automatically adopts future constituent changes. Missing price histories remain missing; the runner does not filter stocks using future outcomes. Historical training data still carries the documented current-cohort and corporate-action limitations.

## Timing

- First decision: September 8 after 16:15 New York time.
- First simulated entry: September 9 at 09:30 New York time.
- Forecast must be saved before 09:25 New York time on the entry date, including a second deadline check after model inference. Late forecasts are not backfilled.
- Rebalance every 21 exchange sessions, for 12 holding periods. First complete period ends October 8, 2026; the declared final endpoint is September 10, 2027 according to the captured exchange calendar.
- Checkpoints at 63, 126 and 252 holding sessions. They are observations, not automatic proof of an edge or reasons to retune the model. No stopping based on interim profitability.
- Both models initially select the same portfolio because neither has prior holdings. Differences should appear from later rebalances.

The active follow-up runs at 13:35 and 13:50 America/Los_Angeles on weekdays. It shares the existing `Alpaca paper trial follow-up` automation; its morning checks remain dedicated to the separate paper trial. The second run can recover a transient capture failure; session/date guards prevent duplicate decisions. This is a Codex thread follow-up, so its host must be available. A missed decision deadline is recorded and stops the study pending review.

## Running and inspecting

Run from the TradingAgents repository:

```sh
PYTHONPATH=. .venv/bin/python scripts/research/prediction_forward_study.py tick --root .research-artifacts/prediction-forward-2026-09-07
```

`tick` uses the configured Alpaca credentials only for GET requests to market data, asset reference and the exchange calendar. On a decision session it captures the full training history; on other sessions it captures the prospective observation interval. It starts the numerical stage in `.venv-prediction-lab` with four numerical threads. Provider responses and source receipts are retained. No paid AI API is needed.

The original three training-data quality quarantines remain in place. HGB parameters, 0.005 replacement advantage, top-third holdings, top-45% retention rule, equal weights, and 11/22 bps costs per traded side remain fixed. There is no fundamental feature or risk-overlay addition in this comparison.

Inspect `status.md`, `status.json`, `protocol.json`, `decisions/`, `decision-locks/`, `observations/`, and `comparison-latest.json`. A fresh decision records the prior decision hash, exact input panel and protocol hashes, scores and selections before outcomes. Each comparison is independently replayed with the second accounting implementation. Changing a frozen dependency or identity blocks execution; preserve the original study before making any separately versioned repair.

## Interpreting observations

Comparisons use observed adjusted daily **open** prices, not broker fills. The current observation endpoint includes hypothetical liquidation costs for comparison; this does not cause an actual sale or change the next decision. Short-period CAGR is omitted. Missing held prices can produce incomplete accounting or gaps, and the report retains those states.

All return reports remain explicitly **adjusted-price diagnostics** pending corporate-action reconciliation. Provider split/dividend/spin-off adjustments are not proof of complete merger, delisting, successor-share or cash-receipt accounting. Asset identity changes or inactive securities block the capture rather than silently substituting another ticker. No live or paper broker-performance claim should be inferred from this study.

At checkpoints, summarize net return, excess versus original HGB and SPY, turnover, drawdown, volatility and evidence gaps. At the final endpoint, assess all declared results and pause the follow-up; an incomplete study is not a successful one.
