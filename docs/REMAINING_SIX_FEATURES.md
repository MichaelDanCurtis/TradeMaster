# Six-feature delivery and evidence ledger

Scope authorized September 6, 2026: finish all six remaining roadmap features.
The existing paper schedule and its exact order permissions remain separate.

| Feature | Required result | Current state |
| --- | --- | --- |
| Independent Astra thesis challenge | Separate model pass over frozen claims and sources; per-claim evidence assessment, falsification tests, provenance, durable results, native model and browser verification | Implemented; native Astra, tests, browser and export verified. See [Thesis challenge](THESIS_CHALLENGE.md). |
| Portfolio stress testing | Saved explicit per-holding and simultaneous shocks, portfolio dollar/percentage effects, cash and concentration, snapshot provenance, native account and browser verification | Implemented; native account, three browser scenarios, independent arithmetic and export verified. See [Portfolio stress](PORTFOLIO_STRESS.md). |
| Richer historical replay | Historically available filings/facts with cutoff receipts, Astra assessment before future prices are revealed, saved decisions and limitations | Implemented; native Astra, browser decision/reveal, source citations, original-document export hashes and persistence verified. See [Historical replay](HISTORICAL_REPLAY_EVIDENCE.md). |
| Broader opportunity discovery | Verified universe coverage beyond 40 symbols, saved screening recipes, incremental collection and comparison explanations | Implemented; native 10,415-entry directory, 50-symbol scan, frozen recipe, stop/resume, browser pagination, exports and restart persistence verified. See [Discovery catalog](DISCOVERY_CATALOG.md). |
| More capable Mac forecasting | Resolve multivariate MLX numerical discrepancies; prove parity and performance with stock, market and volume inputs before enabling | Implemented; 168 original and 48 added numerical comparisons passed, native paired forward/tournament runs and exports verified, about 5.99x warm multivariate inference speedup vs CPU on this Mac. See [MLX qualification](TIMESFM_MLX.md). |
| Complete research-to-paper evidence cycle | Score saved forward forecasts when mature, qualify historical data and evaluate fixed strategies/controls with costs, actual paper lifecycle and five-session assessment | Incomplete; future observations required |

Completion requires source/API/model/browser evidence appropriate to each feature.
A test passing or a UI appearing does not establish model usefulness or broker outcomes.

## First delivery verification

45 focused backend tests and 163 frontend tests passed (208 total); cold TypeScript
and production build passed. The two existing unused-variable warnings remain.
Both new views were exercised against the real local services; no broker orders
were created by either workflow. The approved paper schedule remains separate.
Feature 6 is not complete; the overall goal remains active.

## Feature 6: source readiness and observation boundaries

September 7, 2026 UTC: the Paper trial view now obtains research source readiness
from the preserved, hash-verified captures under the trial's frozen criteria.
It shows the 1,173-session calendar, 4,692 bars per feed, unresolved admission
requirements, and expandable criteria/review fingerprints. Missing, corrupt or
criteria-mismatched source evidence is reported as unavailable. Source coverage
is not presented as historical availability or strategy validation.

Session evidence rejects future-dated observations even when the session's close
has already elapsed. The standalone report command was exercised and its local
module import path repaired. Verification: 28 focused backend tests, 163 frontend
tests, cold TypeScript and production build passed. Native browser navigation,
refresh, source details, expansion and error checks passed against restarted
services. Evidence: `.research-artifacts/paper-trial/ui-verification/`.

The saved plan hash and schedule content hash were checked unchanged, with no
submission attempts. All five sessions remain pending and no terminal broker
order is inferred. Feature 6 remains incomplete: qualifying historical evidence,
fixed-strategy/control evaluation and actual forward/paper outcomes are required.

## Recent-week historical forecast comparison

The user correctly challenged waiting for future prices as a prerequisite for
all useful evaluation. Historical forecast accuracy can be measured now, while
forward paper execution and strict historical data qualification remain distinct.
`scripts/research/replay_forecast_weeks.py` reuses preserved data and the native
local inference process for explicitly selected five-session weeks. It supplies
only the preceding 256 sessions of target/auxiliary inputs to inference; target
outcomes are kept outside the model packet and used afterward for scoring.

Native NVDA MLX comparison for August 24–28 and August 31–September 4, 2026:
stock-only mean absolute error $7.4246 across ten target days, market/volume
$8.0442, flat-price baseline $6.2970 and drift baseline $6.0860. Both variants
narrowly beat flat in the first week and lost in the second. These two weeks do
not show aggregate improvement over simple baselines. They are historical
reconstruction results with possible data revisions/pretraining overlap, not
prospectively issued forecasts or trading-profit measurements.

Evidence: `.research-artifacts/forecast/recent-weeks-replay/` contains the saved
intent, exact numerical model inputs, native output, daily comparisons and report.
Two tests verified outcome/auxiliary-future perturbations cannot change model
cases and incomplete/uncovered weeks are rejected. All four case error scores
were independently recomputed from saved daily predictions and actuals.

## Expanded historical forecast comparison and challenger review

At the user's request, the fixed comparison was expanded to 52 consecutive,
non-overlapping five-session windows per instrument for AAPL, MSFT, NVDA and SPY,
August 25, 2025–September 4, 2026. A frozen intent and source/model/code hashes
preceded inference. Each case received only its preceding 256 sessions. There
were 416 native MLX cases (208 instrument/windows, two variants) and 2,080 daily
prediction rows, covering 1,040 distinct instrument/day outcomes.

Equal-weight price-scaled MAE: stock-only TimesFM 2.2515%, market/volume 2.2889%,
flat control 2.1989%, drift control 2.1848%. TimesFM had 2.39% and 4.09% higher
error than flat, respectively. Strict wins against flat were 99/208 and 88/208;
endpoint-direction accuracy was 50.96% and 49.52%. This cohort shows no aggregate
forecast-accuracy improvement from either TimesFM variant. It is exploratory,
correlated and concentrated in large technology stocks plus SPY, with unknown
pretraining overlap; it does not establish investment returns or universal model
failure. The two earlier NVDA weeks are included and are not an untouched holdout.

Artifacts: `.research-artifacts/forecast/expanded-52-window-benchmark/`, including
intent, exact numerical inputs, native outputs, daily CSV, report and independent
verification. Every case's three error scores and both aggregate baseline-win
counts were recomputed from daily rows. Four tests passed for window construction,
future-data exclusion and missing-data/calendar rejection.

A user-requested research agent reviewed primary sources for alternatives.
Chronos-2 is the first recommended challenger, followed by financial OHLCV model
Kronos-small and univariate Sundial. These are recommendations for comparison,
not demonstrated replacements. See [model challengers](FORECAST_MODEL_CHALLENGERS.md)
for exact versions, sources, Mac support and cross-learning leakage precautions.

## Executed model challengers

At the user's request, Chronos-2, Kronos Small, larger Kronos Base, and Sundial
completed native full-precision local CPU runs on the same saved benchmark.
All 1,040 challenger cases were independently scored and verified; 13 focused
tests passed. Chronos-2 market/volume was best among learned models (2.227%
price-scaled MAE), while flat (2.199%) and drift (2.185%) remained better overall.
Sundial scored 2.362%, Kronos Small 3.563%, and larger Kronos Base 4.591%.
Memory was not limiting (roughly 0.7–1.4 GiB peak per process). No forecasting
accuracy result was treated as paper execution evidence or strategy profit.
See [executed model comparison](FORECAST_CHALLENGER_BENCHMARK.md).
