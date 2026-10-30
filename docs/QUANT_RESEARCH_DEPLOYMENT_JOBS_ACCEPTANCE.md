# Deployment evaluation queue and recovery acceptance

Verified 2026-09-04/05 in isolated local fixtures. This record covers engineering behavior, not strategy profitability, genuine promotion eligibility or remote broker readiness. The complete implementation plan remains active.

Later hardening: [deployment process acceptance](QUANT_RESEARCH_DEPLOYMENT_PROCESS_ACCEPTANCE.md) supersedes the calculation-process limitation below. The original verification counts and browser evidence remain historical to this queue implementation.

## Implemented behavior

- The existing synchronous evaluation endpoint and the new queue endpoint both create durable jobs pinned to deployment revision, approved terms, exact snapshot and UTC-normalized cutoff. Equivalent requests reuse their first job, including terminal results. A repeated terminal request does not claim to have queued new work.
- SQLite transactions and a partial unique index permit one queued/running job per deployment, with a global pending ceiling of 100. Request identity, claimed owner/start/deadline and terminal results are immutable. Another worker cannot claim running work.
- Running work has a 30-second renewable lease and a fixed 120-second publication deadline. Heartbeats cannot extend that deadline. Success and failure publication check ownership inside the writer transaction; proposal publication checks again after calculation and before commit. These are publication bounds, not a hard process-kill guarantee for stalled Python or provider operations.
- API startup and a five-second database-only maintenance loop recover expired leases. A restart alone does not steal a live lease. Expiry retains any saved proposal, marks the job interrupted and pauses the matching active funding revision. It retains capital and positions and does not rerun work or submit an order.
- Explicitly canceling queued work preserves the active deployment. Canceling running work pauses entries and fences late publication. Pending jobs block new buys at exact-order preview and claim. Reductions remain separately reviewable.
- The opt-in deployment worker first reconciles the configured, enrolled account and unresolved native order acknowledgments by client ID. It processes at most one queued job per cycle when reconciliation and drawdown are available. It can request cancellation of entries for paused deployments; reservations remain until broker acknowledgment, and protective parents require review. It has no approval or new-order submission path.
- Quant displays job state, running lease/deadline, failure information and explicit cancellation controls. Pending detail polls every three seconds without overlapping requests, aborts on selection/action changes, and stops when work becomes terminal. Queue copy explicitly requires a separately started worker; no worker availability is inferred.

## Verification

Broad backend command:

```sh
.venv/bin/python -m pytest tests/research tests/ui/test_api.py tests/ui/test_broker_service.py tests/ui/test_alpaca_broker.py tests/ui/test_repository.py tests/ui/test_room_policy.py tests/test_role_models.py -q
```

Result: **348 passed, 12 explicit native integration skips**, 72.98 seconds. Log: `/tmp/trademaster-deployment-jobs-regression.log`. The native LEAN suite was not rerun in this change; prior acceptance is separate.

After the final API duplicate-message change and additional permission test, the focused jobs/failure/API suite passed **16 tests** in 4.40 seconds. Log: `/tmp/trademaster-deployment-jobs-focused.log`. It overlaps the broad suite.

Tests include concurrent claims, immutable requests, wrong-owner rejection, heartbeats reaching the hard publication deadline, expiry during calculation rolling back proposals/programs, running cancellation fencing both failure and success, an actual subprocess exiting after saving a proposal but before job acknowledgment, API startup recovery, queue permission checks, terminal duplicate requests, an unused worker avoiding broker construction, one queued proposal completing without orders, and recovery of a lost native acknowledgment without a second submission.

Full frontend suite: **160 passed**, `/tmp/trademaster-deployment-jobs-webtests.log`. Production build passed, `/tmp/trademaster-deployment-jobs-build.log`, with the same four existing warnings in ActiveProgramsTable, AlgorithmCatalogueRail, BriefWorkspace and SettingsDrawer. Python compilation and tracked whitespace checks passed.

Browser acceptance used the production build and a sanitized, credential-free API harness in `/tmp/trademaster-deployment-jobs-ui`. It created one queued request through Quant, observed waiting/disabled buy controls, ran one actual maintenance cycle through a test-only local harness endpoint, observed automatic completion and a single proposed symbol program, canceled a second queued request through Quant, and reloaded/reselected the deployment. Completed/canceled history and the original proposal persisted. No exact orders or fills were created. No application JavaScript errors, framework overlay or horizontal page overflow were observed. A browser automation click initially only scrolled to an offscreen tab; keyboard focus/Enter corrected navigation before the final reload inspection.

Screenshots: `initial.png`, `queued.png`, `completed.png`, `reloaded.png` in that directory. Deployment: `dep_5b52ec49b2ad42a2ac11eadba5542ee7`; completed job: `djob_f3775f561625453ea88b7e676a195e42`. The harness stubs qualified research evidence and fabricates broker-paper/prospective metadata around synthetic prices. This cannot establish genuine eligibility. The local test-only worker endpoint is not part of the application.

The acceptance browser and both test servers were stopped; ports 8797 and 3000 were verified clear afterward. No remote provider/model request, real order, purchase or commit was made.

## Operator entry point and remaining scope

From the repository root:

```sh
.venv/bin/python -m tradingagents.research.deployment_worker \
  --database-url sqlite:////absolute/path/ui.db \
  --artifacts /absolute/path/artifacts
```

Use the API's exact database/artifact paths. `--once` performs one reconciliation/recovery cycle and at most one queued evaluation; `--reconcile-only` disables evaluation consumption. The polling interval defaults to 15 seconds and accepts 5–300 seconds. An unused installation requires a human-reviewed baseline before broker construction. Do not point fixture acceptance at a real account.

API background maintenance performs local lease recovery only; it does not resolve broker configuration or start the worker. Cancellation/reconnect reconciliation requires the opt-in worker or explicit operator actions. The worker consumes pinned operator requests; it does not choose new observations, schedule daily strategies, ingest provider data, or authorize orders. A stalled operation can retain process resources beyond its publication lease, but it cannot publish late evidence or reuse that expired job. Process isolation/termination and recovery health reporting remain operational hardening work.

Remaining release work includes verified provider provenance/capabilities, genuine and labelled datasets, paired event/calibration acceptance, strategy-design assistance, actual funded/rounded risk, deployment equity/returns and execution-delay attribution, protective/corrected-source accounting, history capacity, and the full genuine evidence-to-paper walkthrough. Real-provider paper verification remains conditional on configuration and explicit human order approval.
