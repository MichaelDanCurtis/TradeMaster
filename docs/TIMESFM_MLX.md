# TimesFM 3 on Apple Silicon

TradeMaster now has an optional, offline MLX/Metal backend for **stock-only and stock + SPY + volume**
Forecast Lab experiments. CPU remains the default. Select the desired inputs and
**Apple GPU · MLX** in Research → Forecast Lab. Forecast Tournament also accepts
paired MLX runs. Both the 5-session
and 20-session horizons are supported, using the same 256 observations and original
FP32 checkpoint. This accelerates inference; it does not improve the model's
predictive accuracy or confer trading authority.

## Implementation and attribution

This integration reuses [Rachit Shah's mlx-tsfm port](https://github.com/rachittshah/mlx-tsfm)
at commit `be63b266d7065177c8bd5b163a954d3ab3c66221`, rather than claiming a new model
implementation. Its code is MIT-licensed and its NOTICE credits the Google TimesFM
implementation. Those files remain in the installed source package. Model weights
retain their separate original LICENSE and are neither converted nor redistributed.

Our adapter adds strict native safetensors loading, offline execution, architecture
and source-pin checks, input validation, matching Google quantile sorting and median
selection, completed-GPU timing, and TradeMaster's existing evidence receipts.
[MLX strict loading](https://ml-explore.github.io/mlx/build/html/python/nn/_autosummary/mlx.nn.Module.load_weights.html)
checks every parameter name and shape. Explicit evaluation is necessary because
[MLX evaluates lazily](https://ml-explore.github.io/mlx/build/html/usage/lazy_evaluation.html).
No PyTorch dependency is installed in the MLX environment.

Install after the base model:

```sh
bash scripts/research/setup_forecast_mlx.sh
```

The environment pins MLX/Metal 0.32.2, NumPy 2.5.2, safetensors 0.8.0 and the port's
exact Git commit. A run checks actual Metal availability and fails without fallback.
An installed environment is not displayed as proof that GPU inference succeeded.

## Measured on this Mac, September 6, 2026

Apple M4 Max, 128 GB unified memory. FP32 throughout, Google checkpoint revision
`43046b85ec22d584a13f8098c2ed39c889e129c2`; reference Google code commit
`0df95ae62085a6ac0d0afd1ad40dee2e6c1356ab`; PyTorch 2.14.0 with eight CPU threads.
Three sequential fresh processes per backend and horizon, rotating backend order.
Filesystem and Metal shader caches were **not** cleared. No concurrent GPU benchmarks.

| Stock-only measurement | PyTorch CPU | PyTorch Metal | MLX Metal |
| --- | ---: | ---: | ---: |
| Warm median inference | 58.26 ms | 45.15 ms | **9.70 ms** |
| Warm p95 inference | 64.60 ms | 48.03 ms | **12.03 ms** |
| Median import + weight load | 1.029 s | 1.199 s | **0.096 s** |
| Median peak process RSS across full suite | 2,737 MB | 2,742 MB | **1,354 MB** |

Each warm statistic contains 78 completed forecasts, excluding the first call of
each input shape in each process. Process RSS includes some but not all accelerator
memory and is not total system memory. Load/RSS measurements come from processes
that also exercised experimental covariates. These are local measurements, not
cross-hardware guarantees. The very first observed MLX inference took **6.66 s**
while compiling; that cold call is preserved separately. Warm speeds do not describe
first installation or end-to-end market-data capture latency.

### Numerical qualification

Each horizon used 28 cases: nine real stock windows (three each of NVDA/AAPL/MSFT),
the same nine with SPY/volume, and five synthetic signals with/without auxiliary
inputs (constant, trend, oscillation, step, penny price). Repeated comparisons test
all nine quantiles and the point forecast against the CPU reference. The declared
tolerance was absolute $0.001 or relative 0.00001 (Python `math.isclose`); it was not relaxed after results.

- **Stock-only MLX: 84/84 case comparisons passed**, representing 28 distinct
  case/horizon combinations repeated three times. Maximum difference: **$0.0000916**.
- Real stock-plus-SPY/volume cases also passed, but two synthetic auxiliary-input
  cases failed at both horizons. Maximum MLX difference: **$0.07658**; PyTorch Metal
  also differed from CPU on those cases, by up to **$0.01939**.
- At this initial qualification, the API and UI kept MLX covariate/paired requests
  disabled. The discrepancy is resolved in the September 7 work below.

The failing cases contain an almost perfectly linear auxiliary series. The
September 7 stage captures below establish the first divergence and verify the
repair without loosening the declared tolerances.

## Reproducing and inspecting evidence

Local numerical fixtures and full per-case results are retained under
`.research-artifacts/forecast/mlx-benchmark/`. `input-5.json` and `input-20.json`
contain captured past values and synthetic cases, without credentials or future
outcomes. The saved development forecast receipts retain market-data provenance.

```sh
.venv/bin/python scripts/research/benchmark_forecast_backends.py \
  .research-artifacts/forecast/mlx-benchmark
```

`report.json` records tolerances, input/model/runner SHA-256 hashes, actual runtime
versions, all timings, case-level errors and failures. The original report separates
stock qualification from covariate failures. The benchmark now requires **both**
MLX variants to pass before returning success. Initial one-off cold results are `mlx-5.json`.
In-app jobs use the selected runner's own hash and record `mlx_port_revision`,
`mlx_version`, precision, compilation setting, and peak MLX allocation. The evidence
ZIP preserves these alongside the normal data and prediction receipts.

## Multivariate repair, September 7, 2026

Stage captures of the unchanged Google CPU and upstream MLX models established
that the first consequential divergence was the FP32 reduction order used to fit
a linear trend. In the synthetic SPY-like series, the fitted slope differed by
0.00036621 and the intercept by 0.00018311. These small residual differences were
amplified by standardization: a normalized input differed by 2.70879 before the
transformer. Supplying CPU coefficients to the otherwise unchanged MLX model
removed both failures. This was a diagnostic intervention, not the shipped path.

The shipped adapter computes the small detrending reductions in NumPy FP32 with
the pinned PyTorch ARM NEON order for exactly 256 observations. The algorithm
specializes [PyTorch's contiguous sum implementation](https://github.com/pytorch/pytorch/blob/08187d9e0fba026dc8217405802ab5381dc88d90/aten/src/ATen/native/cpu/SumKernel.cpp).
Its [BSD license](third-party/PYTORCH_LICENSE.txt) is preserved. This deliberately
matches reference rounding; replacing it with a higher-precision fit would change
the reference behavior. The remaining normalization, transformer and output heads
run on MLX Metal. No PyTorch dependency was added to the MLX environment and no
weights were altered, quantized or converted.

The adapter requires Apple Silicon macOS, NumPy 2.5.2 and MLX 0.32.2, in addition
to the existing source/checkpoint pins. Saved runtime receipts identify
`numpy-fp32-pytorch-arm256-v1` and the reference PyTorch revision. The runner hash
covers the preprocessing code. Shape or version changes fail rather than silently
using a different reduction or device. This qualification is local to the stated
runtime and input contract; it is not a claim of universal backend equivalence.

Regression evidence includes eight captured CPU preprocessing fixtures, exact
reduction agreement on 3,000 random 256-value series, the unchanged full stock and
covariate qualification suite, and 24 additional near-linear cases at each horizon.
The added cases vary noise and target price scales from 0.001 to 10,000. The same
absolute 0.001 / relative 0.00001 `math.isclose` criterion applies throughout.

Reproduce the final suites into a new output folder to preserve earlier evidence:

```sh
# First copy input-5.json and input-20.json from the original mlx-benchmark folder.
.venv/bin/python scripts/research/benchmark_forecast_backends.py OUTPUT_FOLDER
.venv/bin/python scripts/research/check_mlx_near_linear.py ANOTHER_OUTPUT_FOLDER
```

Stage-capture tooling is `scripts/research/diagnose_forecast_preprocessing.py`.
The diagnostic `--reference-trend` option explicitly requires a CPU stage archive;
it is not used by the application or the qualified adapter. Historical diagnosis
artifacts are in `.research-artifacts/forecast/mlx-diagnosis/`.

### Final qualification and native application checks

Final artifacts: `.research-artifacts/forecast/mlx-multivariate-final/report.json`
and `.research-artifacts/forecast/mlx-near-linear-final/report.json`. Their original
input/model hashes and tolerances match the first qualification. The original
suite passed **168/168 MLX comparisons**, and the additional suite passed **48/48**.
Maximum absolute difference in the original MLX suite was 0.00009155 across all
quantiles and point forecasts. The final benchmark fails if either MLX input
variant fails. PyTorch Metal still differs on the earlier auxiliary edge cases;
this repair and qualification apply to the MLX adapter.

For stock + SPY + volume, completed warm inference medians were **15.265 ms MLX**
and **91.388 ms CPU**, about **5.99 times faster** on this M4 Max. Each median
contains 78 warm samples across both horizons and three fresh processes. First
calls are excluded from warm summaries, original cold evidence is retained, and
filesystem/Metal caches were not cleared. This measures model inference, including
preprocessing, rather than end-to-end data collection or predictive accuracy.

Native browser-created runs:

- Paired five-session NVDA forward forecast
  `forecast_1b419806e5404e258fa5c246779a7a45`, saved before the September 8 first
  target open, with targets September 8–14. Outcomes remain pending.
- Paired 20-session NVDA historical tournament
  `desk_3d9ee28b43344424b58f3106b7fc35b2`, child
  `forecast_827981d5e90b4c899c2094a20703a1ec`, with six development cases.

All eight application cases were independently rerun through the unchanged CPU
child using the exact saved numerical inputs. Every point and quantile passed the
original tolerance; maximum differences were 0.00006104 (forward) and 0.00002289
(development). Both saved outputs use the exact adapter hash in the final
benchmark. Exported evidence object hashes passed, saved results were unchanged
after restart, and both variants rendered in the browser. Native exports,
comparison checks and screenshots are in `mlx-native-verification/` under the
forecast artifact directory.

47 focused backend/numerical tests and 163 frontend tests passed; cold TypeScript
and production build passed. The existing two unused-variable warnings remain.
The approved paper schedule and trial plan are unchanged, with zero schedule
attempts at this verification. No result here establishes trading profitability.
