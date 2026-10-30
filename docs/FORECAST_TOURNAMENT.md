# TimesFM tournament

Open **Research → Forecast tournament**. Choose 1–6 stocks, 5 and/or 20 sessions,
stock-only or paired SPY/volume inputs, an explicit market-data feed, and CPU,
PyTorch Metal, or qualified stock-only MLX. The default is three stocks, both
horizons, paired inputs, SIP and CPU: six sequential jobs and 36 forecast windows.

## Frozen definition and bounded execution

The immutable definition is saved before the first child job. It pins the model
revision/checksums, forecasting/scoring code, input settings, historical scope,
scoring formula and condition thresholds. Requests are idempotent. The existing
Forecast Lab's unique active-job slot prevents concurrent local inference. A
manual forecast can occupy that slot; the tournament then waits for it.

Every child uses the existing development experiment: 256 context sessions and
three non-overlapping, 20-session-spaced late-2023 target windows. A five-session
forecast uses the same cutoffs with shorter targets. The saved strategy's 2024
validation period and later holdout are not read. This is still a reconstruction:
present-day adjusted prices and identity, selection bias, and unknown TimesFM
pretraining overlap prevent treating these results as unseen evidence.

All horizons for a symbol must have identical normalized bars and calendars.
Changed data excludes the affected child from aggregation and retains its result
and reason. Model/code changes interrupt the batch. Missing and failed jobs are
never zero-error results. A stopped batch launches no more children; an already
running child can finish and remains accessible in Forecast Lab. Its live state
and available evidence link remain visible in the tournament. An API restart
interrupts a batch, recovers saved child identities, and never automatically
repeats inference. One local API process is supported.

## Reading the results

- Each window's mean absolute price error is divided by its final context close.
  Scores are averaged equally across stock/windows, so a high-priced stock does
  not dominate simply because dollar errors are larger. This is normalized MAE,
  not mean absolute percentage error against each future actual price.
- Last-price and linear-drift baselines share each forecast's context and targets.
  Relative improvement is computed from the aggregate normalized errors. A
  zero-error baseline gives an undefined relative improvement, never infinity.
- Horizons and input variants are separate. Wins use strictly lower error; ties
  are not wins. All per-window losses remain visible.
- Band coverage, normalized width, and the central 80% interval score are shown.
  Interval score penalizes both wide bands and misses. These outputs do not
  establish calibrated uncertainty.
- Conditions use only preforecast prices: trailing 60-session return above 5%
  is rising, below -5% falling, otherwise sideways. Trailing 20 daily-return
  sample volatility is annualized by sqrt(252); 40% is the high-volatility
  boundary. These fixed descriptive bins are not a trained regime classifier.
- Inference time excludes imports, model loading, source requests and queueing.
- Partial/canceled/failed batches stay provisional. Complete coverage means all
  configured jobs were scored, not that the model is useful or the sample is
  representative. Different stocks share market moves; horizons can share target
  days, and these observations must not be counted as independent evidence.

Download the tournament JSON for the frozen definition, cells, cases, leaderboard
and hashes. Each completed child links to the existing evidence ZIP with its
inputs, predictions and raw provider receipts. Results do not create orders,
allocations, strategy approvals or model calls through Astra.

## First native verification — September 6, 2026 Pacific

The browser submitted AAPL/MSFT/NVDA, both horizons, paired inputs, SIP, CPU.
All six local model jobs completed, producing 36 forecast windows. Native result
and source hashes were verified, and normalized forecast errors and leaderboard
means were independently recomputed from saved actuals/predictions. The JSON
export matched the saved detail.

| Horizon | Inputs | Normalized MAE | Last-price MAE | Improvement vs last price | Wins vs last price |
| --- | --- | ---: | ---: | ---: | ---: |
| 5 sessions | Stock only | 2.541% | 2.967% | 14.39% | 6/9 |
| 5 sessions | Stock + SPY + volume | 2.580% | 2.967% | 13.05% | 5/9 |
| 20 sessions | Stock only | 3.854% | 4.967% | 22.40% | 7/9 |
| 20 sessions | Stock + SPY + volume | 4.302% | 4.967% | 13.39% | 6/9 |

The stock-only configuration had lower aggregate error in this small sample.
That does not establish future superiority or a profitable strategy. Four of the
six possible condition bins occurred; absent conditions are not invented.

Definition: `59b0884737ebc2027c8f6c3538fdaa9df04d4ca9aa0620e5845b0aed3d3acf1c`.
Summary: `7aa7b25ef414fc5715ce77acd4d5b006afb7d1ae383d241b241afbd911487d37`.
Native detail and verification are retained in
`.research-artifacts/forecast/tournament-verification/`.

The 36 focused tournament/forecast tests and all 163 frontend tests passed.
Production build passed with two pre-existing unused-variable warnings in
unrelated components. Paper execution attempts remained zero and the approved
trial plan was unchanged.
