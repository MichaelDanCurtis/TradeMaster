# Local Forecast Lab

Open **Research → Forecast Lab**. Choose a stock, 5 or 20 exchange sessions,
stock-only, stock + SPY + volume, or a paired comparison, and CPU or Apple GPU. Every run is explicit.
The runtime is isolated from the API's Python environment and has no trading interface.

## Installed model and reproducibility

An optional **MLX/Metal stock-only backend** is available on Apple Silicon. See
[TimesFM MLX qualification](TIMESFM_MLX.md) for setup, measured performance, numerical
parity, and the current SPY/volume limitation. CPU remains the default.

- Model: Google's `timesfm-3.0-pytorch`, revision `43046b85ec22d584a13f8098c2ed39c889e129c2`.
- Code: `google-research/timesfm`, commit `0df95ae62085a6ac0d0afd1ad40dee2e6c1356ab`.
- Local environment: `.venv-timesfm`, Python 3.12, torch 2.14.0, numpy 2.5.2.
- Setup: `bash scripts/research/setup_forecast.sh` from the repository root; requires `uv` and the existing `.venv` interpreter.
- Weights, model configuration and original LICENSE remain under the ignored
  `.research-artifacts/forecast/model` directory. This prototype is for local research evaluation.
- `runtime.json` records SHA-256 checksums. Every run verifies model files and the
  child verifies the installed source commit. Outputs record actual package versions,
  device, input/result hashes and inference-runner hash.
- Exact input packets, raw provider responses, outputs and scoring receipts are
  content-addressed under `.research-artifacts/forecast/objects`.

The offline model process receives only 256 closing prices and, optionally, two
aligned past-only series (SPY close and the stock's volume). No outcomes or provider
credentials enter its input or environment. One local job can run at once. Inference
has a 180-second wall-clock limit and uses eight CPU threads. GPU failure stays a
failure; it does not silently switch devices. Single API process is the supported
deployment. On API restart, unfinished jobs become interrupted and are not retried.

## Dated data and experiments

The existing Alpaca market-data credentials supply paginated daily bars and a GET-only
request to the paper exchange calendar. SIP/IEX selection is explicit. Price basis is
split-adjusted USD close, with symbol remapping disabled (`asof=-`). No dividends are
reinvested. See [Alpaca historical bars](https://docs.alpaca.markets/us/reference/stockbars)
for feed, pagination and adjustment semantics.

The current New York calendar day's bar is excluded, including after market close,
because daily aggregates may still change. Every context date must have a valid bar;
missing sessions are rejected rather than interpolated. Calendar targets exclude
weekends and exchange holidays. A forward forecast is prospective evidence only if
its completed result is saved before its first target session opens. Late issuance
is labeled explicitly and remains excluded from prospective evidence.

The development experiment uses three non-overlapping, 20-session-spaced cutoffs in
late 2023, each with exactly 256 prior sessions. A 5-session run uses the same cutoffs
and shorter outcomes. This is an independent exploratory TimesFM experiment; it does
not modify the existing trading strategy's validation/holdout or promotion rules.
The model's pretraining overlap is unknown. Present-day revisions and split adjustments
mean the historical data is a reconstruction, not point-in-time unseen evidence.

Comparisons report mean absolute price error against last price and a linear drift
baseline, plus observed coverage of the model's 10th–90th percentile band. Paired
experiments hold the capture, target dates, model and device constant across both
input variants. Their summary weights windows by the number of outcomes; a
zero-error baseline produces an undefined relative improvement, not infinity.

Interval quality reports mean band width and the central 80% interval score:
`upper - lower + 10 * max(lower - actual, 0) + 10 * max(actual - upper, 0)`.
Lower is better: an excessively wide band cannot win simply by covering everything.
A quantile
band is not a calibrated confidence guarantee. These are forecast metrics, not net
trading returns or proof of investment edge.

## Prospective outcomes

Use **Check observed outcomes** after the final target New York date has ended.
Until then, status is pending and no zero-valued metrics are fabricated. The original
forecast remains preserved. A new capture must contain every target and agree with
the original context prices; revisions or subsequent splits produce `basis_changed`
instead of an invalid comparison. Scoring receipts preserve both source and forecast
hashes. The API also checks saved forecasts automatically, at most one matured
forecast per minute. Pending or failed captures back off for 24 hours; changed
price bases await manual review. Successful scores are reused. Pause/resume is
durable in the local database. The collector operates only while the API is running;
it never invokes the forecast model or places an order. Manual checking remains available.

## Exports and research briefs

Every completed result offers a predictions CSV and an evidence ZIP. Future actual
values stay blank in CSV. The archive contains the forecast record, numerical
predictions, and recursively referenced source/input/output/scoring receipts. Each
`objects/` filename is the SHA-256 hash of its bytes. It excludes model weights and
provider credentials.

An explicitly requested Astra brief can include the latest saved forward forecast
for that symbol, if issued within the preceding seven days. This is labeled
`model_forecast` and includes model revision, dates, result hash, input variants,
quantiles and outcome state. It does not launch a forecast or another data scan.
Stale, future-dated, wrong-symbol or unreadable evidence is excluded with a gap.
Prompt rules keep predictions distinct from company facts and observed outcomes.

## Verified on this Mac — September 6, 2026

Apple M4 Max, 128 GB unified memory. Synthetic 256-point/20-session cold-process test:

| Device | Load + imports | First inference | Peak process RSS |
| --- | ---: | ---: | ---: |
| CPU | 4.94 s | 0.074 s | 2.70 GiB |
| Apple GPU (MPS) | 1.25 s | 2.02 s | 2.68 GiB |

These are individual runs, not statistical performance estimates. Import/filesystem
caches affect load time; MPS compilation affects first inference. GPU allocations
are also reported separately and must not be naively added to process RSS because
unified-memory accounting can overlap. CPU is the default for these small jobs.

Actual NVDA SIP inference was also verified on CPU (stock-only) and MPS (SPY + volume).
Three stock-only 2023 cases had MAE $2.765 / $2.940 / $0.735 versus flat-baseline
$1.993 / $5.463 / $1.605: better in two windows, worse in one. Results are exploratory.
A 20-session forward forecast was saved on September 6 for September 8–October 5,
2026; a 5-session forecast for September 8–14 was also created and inspected through
the browser. Both have pending outcomes. These results do not change the approved Alpaca paper
orders or create new scheduled trades.

See [the unattended-work report](OVERNIGHT_RESEARCH_REPORT.md) for the subsequent
paired experiments, additional tests and browser verification.

## Batch comparisons

The [TimesFM tournament](FORECAST_TOURNAMENT.md) adds frozen multi-stock batches,
separate 5/20-session comparisons, normalized baseline errors, historical-condition
breakdowns, retained failures and exportable evidence. Open Research → Forecast
tournament. It shares this lab's existing single-job runner and development scope.
