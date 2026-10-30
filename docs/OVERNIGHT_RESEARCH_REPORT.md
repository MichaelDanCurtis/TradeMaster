# Research improvements — September 6, 2026

The Forecast Lab now runs paired experiments from the same captured data and
device, scores matured outcomes automatically while the API runs, exports
predictions/evidence, and supplies dated model-output evidence to explicitly
requested Astra briefs.

## What the paired experiments showed

Five-session horizons, three fixed development cutoffs in late 2023, 256 prior
sessions per cutoff, Alpaca SIP split-adjusted closes, and CPU inference. Each
variant has 15 daily errors across three windows; those errors are not independent.

| Symbol | Flat baseline MAE (USD) | Stock-only MAE | SPY + volume MAE | What adding inputs did |
| --- | ---: | ---: | ---: | --- |
| NVDA | 1.7453 | 1.4024 | 1.3307 | Reduced average error |
| AAPL | 4.1040 | 3.6975 | 4.0124 | Increased average error |
| MSFT | 8.8090 | 8.0855 | 8.4875 | Increased average error |

The stock-only variant beat the flat baseline in two of three windows for every
symbol. Added inputs were not consistently better. In NVDA, the added-input band
covered every observed outcome, but its interval score was worse (4.60 versus 4.29)
because its bands were wider. This is why both accuracy and band quality are shown.

These reconstructed historical windows may overlap model pretraining. They do not
establish investment profitability or authorize any execution change.

Development experiment IDs:

- NVDA: `forecast_bcc7d6ca09fa42189299eef48ea999f7`
- AAPL: `forecast_d2d0c25ed2424a0988a66400526b269b`
- MSFT: `forecast_ff2dfedd6138479f94e2581f789b2507`

Paired forward forecasts, saved before the first target session, cover September
8, 9, 10, 11 and 14:

- NVDA: `forecast_292b4ecf7b014b32908404a0ecabf95e`
- AAPL: `forecast_3d211262093a43028a7de93d01f13304`
- MSFT: `forecast_d02223247c5e4ca996319e62f65e0204`

Their outcomes remain pending. The automatic collector can score them after the
September 14 New York date ends and all required bars are available. The previously
saved 20-session NVDA forecast continues through October 5.

## Verification

- All 119 backend regression tests passed, covering the API, explorer, research
  desk, Astra briefs, forecast lab and paper-trial report.
- Frontend: 163 tests passed; TypeScript and the production build passed.
- Real paired inference completed for all six development/forward jobs above.
- Browser: explorer/desk/forecast navigation, monitor timestamps, paper-trial
  evidence refresh, paired comparison table, variant/cutoff selection, automatic
  scoring pause/resume, and export link targets were checked.
- CSV endpoint returned ten paired forward rows with blank actuals. The ZIP
  endpoint returned five source/input/output artifacts whose hashes all verified.
- Invalid symbols, unsupported horizons and invalid scoring preferences returned
  422; an unknown export returned 404. None created another forecast job.
- An isolated test database used a real model subprocess, terminated it with
  SIGTERM, and verified `interrupted`, no published output, and a finished worker.
- The production API, research worker, deployment worker and scheduler reported
  healthy after restart. Automatic outcome scoring was restored to enabled.
- The approved paper schedule remains active. Both exact NVDA orders remain
  approved with no broker submission receipts, and all five trial dates are pending.

No additional overnight Codex heartbeat was created: this task already has the
paper-trial follow-up, and the app permits one attached heartbeat. That existing
follow-up remains unchanged. The new outcome collector runs inside TradeMaster,
independently of Codex, whenever the local API is running.
