# Executed forecast challenger comparison

Completed September 7, 2026 on the local M4 Max / 128 GB Mac. All four challenger
runs completed, with 1,040 total model cases and no missing case outputs.
The fixed historical set remains 208 instrument/windows (52 each for AAPL, MSFT,
NVDA and SPY), with five target sessions and 256 preceding sessions per window.
Chronos has two input variants; each other challenger has one. Models are evaluated
against the same 1,040 distinct instrument/day outcomes; repeated predictions do
not create independent observations.

| Method | Price-scaled mean absolute error | Relative error versus flat |
| --- | ---: | ---: |
| Drift baseline | 2.185% | -0.64% |
| Flat baseline | 2.199% | reference |
| Chronos-2, market/volume | 2.227% | +1.29% |
| Chronos-2, closes | 2.242% | +1.95% |
| TimesFM-3, closes | 2.252% | +2.39% |
| TimesFM-3, market/volume | 2.289% | +4.09% |
| Sundial, closes | 2.362% | +7.42% |
| Kronos Small, OHLCV | 3.563% | +62.01% |
| Kronos Base, OHLCV | 4.591% | +108.81% |

The larger Kronos Base did not improve upon Small here. Chronos-2's market/volume
version is the best learned model in this comparison, but does not beat the
simple baselines overall. Its paired time-block bootstrap interval for improvement
over flat spans -3.92% to +1.56%, so a small difference should not be overinterpreted.
None of these results establishes strategy profit or a persistent trading edge.

## Native execution and model sizes

- Chronos-2: full 119.48M released model, native CPU FP32; native median forecast;
  cross-learning disabled and one window per call. Peak process memory 827 MiB.
- Kronos Base: full 102.31M model plus 3.96M tokenizer, native CPU FP32; 10 sampled
  paths with temperature 0.6, top-p 0.9, top-k 0, max context 512 and clip 5.
  Peak process memory 1,355 MiB. Small uses the identical settings and inputs.
- Sundial: full 128.33M model, native CPU FP32; median of 20 generated paths, native
  input-only normalization and configured 50 flow steps. Peak memory 1,268 MiB.
  Its secondary sample-mean estimator also lost to flat (2.390% error).
- All stochastic runs use seed 59137 plus the fixed benchmark case index. No seed,
  model, sample count or window selection was changed after observing scores.
- No larger official Chronos-2 or Sundial release was found. Kronos Large is listed
  but unreleased; Base was the largest downloadable official checkpoint verified.
  See [sources and revisions](FORECAST_MODEL_CHALLENGERS.md).

Kronos uses richer historical inputs: open/high/low/close, volume, and derived
turnover computed as volume times the source VWAP. Turnover is not mislabeled as
reported exchange dollar volume. Only the target session dates enter the model;
no future OHLCV values are supplied. The official predictor normalizes each
historical channel independently. It averages its decoded sample paths natively.
Models/tokenizer are explicitly in evaluation mode and inference uses no gradients.

Chronos/Kronos use the isolated `.venv-forecast-challengers` environment;
Sundial uses `.venv-sundial` with Transformers 4.40.1 for its pinned generation API.
Exact package freezes, verified Hugging Face file hashes and revisions are under
`.research-artifacts/forecast/challenger-models/`. Weight LFS SHA-256 and ordinary
Git blob SHA-1 were compared with the pinned Hub metadata before inference.
Only download/setup used network access. The child model process runs offline
without provider credentials or target outcomes. Kronos source commit is
`67b630e67f6a18c9e9be918d9b4337c960db1e9a`.

## Verification and artifacts

`.research-artifacts/forecast/challenger-benchmark/` contains:

- Per-model frozen intent, exact inputs, append-only per-case journals, completed
  native output, and scores. Existing run directories cannot be overwritten.
- `input-verification.json`: all 1,040 contexts match the fixed benchmark, original
  outcomes match preserved SIP source bars, and no target values enter inference.
- `verification.json`: independently recomputed all 1,040 native case errors,
  checked aggregates, fixed seeds, journal/final equality and file fingerprints.
- `comparison.md`, `comparison.json`, `comparison.png` and `comparison.svg`.
- `code/`: copies of the local runner, preparation, scoring and report scripts.

Thirteen focused tests pass, including future-value mutation, missing dates,
changed outcome/input evidence, duplicate/missing case outputs, nonfinite values,
wrong horizons and independent expected scoring. No UI/API or broker changes were
needed for these experiments. Concurrent runs mean elapsed times are observations,
not a controlled hardware speed comparison.

Entry points: `run_forecast_challenger.py --kind <chronos2|kronos-base|kronos-small|sundial>`,
`score_forecast_challengers.py --kinds ...`, and `report_forecast_challengers.py`, all
under `scripts/research/`. Run preparation intentionally refuses existing output
directories; preserve these experiments when planning any later settings change.

The bootstrap is descriptive: 5,000 moving-block draws with seed 71397, four
consecutive windows per block, with contemporaneous stocks retained together.
It does not account for training uncertainty, alternative seeds, selection of
this stock cohort, or unknown pretraining overlap. Current source revisions,
correlated technology exposure and historical reconstruction remain limitations.
