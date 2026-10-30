# Deployment supervisor and health acceptance

Verified 2026-09-05 in disposable local databases. Synthetic source/account/promotion fixtures verify software behavior only; no genuine investment or broker-paper result is claimed.

## Implemented behavior

The explicitly started deployment worker now supervises each complete observation, entry-cancellation and queued-evaluation cycle in a separate process. A fixed cycle timeout covers provider construction (including Keychain lookup), account reconciliation and cancellation orchestration as well as the already-isolated target calculation. The default is 180 seconds, configurable from 10–600 seconds. The existing evaluation job keeps its independent 120-second deadline and renewable lease.

The supervisor monitors a monotonic deadline, bounds the completion receipt and kills/reaps its cycle process on failure or timeout. A private pipe terminates a cycle when its supervisor dies; the child also has a kernel wall-clock timer. Nested calculation retains its own supervisor-death and publication protections. A completed cycle never reuses a terminal evaluation job. Cleanup can interrupt only running claims bearing that exact cycle identity, plus already expired leases; another worker's live claim remains untouched. Interrupted matching deployments retain funding/positions and require fresh review. Existing cancellation acknowledgment and exact-order approval rules still apply.

Only the enabled paper provider's explicitly selected environment credential is forwarded to the provider cycle. Keychain resolution stays in that bounded child. Other model/provider environment secrets and dotenv loading are excluded. The configured broker must resolve to the supported paper adapter; an enrolled but unconfigured installation reports observation unavailable rather than substituting a fixture account. An installation without an approved baseline performs no broker construction.

A new additive worker table records process identity, mode, loaded supervisor build, phase, account scope, cycle deadline, last cycle result and last supervisor heartbeat. Heartbeats continue during the pause between cycles. The read-only runtime API reports evaluation versus reconciliation-only mode, queued/running counts, account scope, stopped state and stale heartbeats after 20 seconds. Child progress cannot update the parent heartbeat or overwrite a later cycle. A heartbeat establishes supervisor presence, not current account reconciliation or order authority.

Quant shows this state without disabling the ability to queue work while offline. Details retain the last observation timestamp, drawdown availability, cycle limits and prior stopped workers. Polling is abortable and sequential, and changing the selected deployment changes the account scope.

## Verification

- Full backend regression: **418 passed, 12 explicit native Docker skips**, 95.91 seconds. `/tmp/trademaster-supervisor-regression.log`. The expected local SDK warning concerns the fabricated `pinned-test-model` identifier.
- The eight new supervisor tests cover health scope/modes/staleness, late child updates, selective credential forwarding, the actual CLI against an unused database, unconfigured-provider rejection, a real successful cycle with nested calculation, cycle timeout with ownership-limited recovery, runtime API permissions, and actual supervisor death with child termination/expiry recovery. Some tests cover multiple scenarios. The preceding focused seven-test run passed before the supervisor-death case was added; final broad regression includes all eight.
- Frontend suite: **160 passed**, `/tmp/trademaster-supervisor-webtests.log`. Final production build passed with the same four existing nonfatal warnings; `/tmp/trademaster-supervisor-webbuild.log`. Python compilation and whitespace checks passed.
- Browser acceptance observed a selected account with one queued job and no worker; started the real supervisor using an explicitly injected synthetic provider child; observed its heartbeat, account timestamp and automatic completion; stopped it and observed stopped status. After restarting the API against the same database and starting a new supervisor, Quant retained the completed job and displayed the new worker alongside the stopped one. No JavaScript error, application alert or page overflow appeared.

The saved browser database contains **one completed evaluation and zero exact orders**, with both test workers stopped after cleanup. The initial positive funding/source metadata and child paper-provider metadata are deliberately fabricated acceptance inputs. The test wrapper is under `/tmp`, not an application API or provider fallback.

Artifacts: `/tmp/trademaster-supervisor-ui/{initial,offline,connected,stopped,restarted}.png`, `references.json`, and the retained SQLite database. The browser, test workers and API/web servers were stopped after verification. No remote broker/model request or purchase was made.

## Operator entry point

```sh
.venv/bin/python -m tradingagents.research.deployment_worker \
  --database-url sqlite:////absolute/path/ui.db \
  --artifacts /absolute/path/artifacts \
  --interval-seconds 15 \
  --cycle-timeout-seconds 180
```

Use the API's database and artifact store. `--once` runs one bounded cycle and records the supervisor as stopped on exit. `--reconcile-only` skips queued evaluations; it retains the existing paused-entry cancellation checks. Starting this worker does not grant order approval or create strategy observation snapshots.

## Remaining scope

Provider-backed prospective dataset ingestion/scheduling, genuine labelled/calibration evidence, protective-child/corrected-source accounting, history capacity, funded pause/resume and the full release walkthrough remain open. Synchronous operator API provider calls and the standalone legacy accounting observer continue to use their provider transport timeouts; the whole-cycle process boundary described here belongs to the deployment worker entry point. Remote provider semantics and credentials were not validated by these synthetic tests.

Kernel timers bound the fallback lifetime if a supervisor-pipe watcher cannot run promptly; these tests do not establish instantaneous cleanup under every operating-system failure. A timeout cannot revoke a broker cancellation already accepted remotely, so existing retained reservations and reconciliation remain authoritative. No new-order submission capability was added.
