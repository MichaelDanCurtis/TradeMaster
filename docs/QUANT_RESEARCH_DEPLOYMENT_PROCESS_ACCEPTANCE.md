# Deployment calculation process acceptance

Verified 2026-09-05 using isolated synthetic account, funding and prospective-source fixtures. This is software acceptance, not genuine promotion or broker-paper evidence.

## Implemented boundary

Both queued worker evaluations and the synchronous deployment evaluation API now execute target/risk calculation in a separate Python process. The child opens the existing persistent SQLite database and exact artifact store, reads the claimed job, and validates its owner, request, reconciliation and loaded calculation build. It receives no broker adapter, inherited credentials or model authority. Standard output is discarded and the result is a bounded receipt referencing the saved evaluation.

The parent monitors cancellation, ownership, lease and fixed deadline through a read-only connection with a short database timeout. A monotonic deadline prevents wall-clock adjustment from extending process runtime. On loss of authority or an exception, it kills and reaps the isolated calculation process. The child also has a kernel wall-clock timer and a private supervisor pipe; supervisor death closes the pipe and terminates the child's process group. These mechanisms do not retry expired work. Existing durable recovery retains evidence, pauses the matching deployment revision and requires review.

Calculation no longer holds the database writer lock. It reads a coherent snapshot, closes it, computes targets/risk, and then enters a short publication transaction. Before writing any proposal or symbol program, it rechecks job authority, current deployment revision/state/terms, account reconciliation freshness and execution changes, latest evaluation, guidance execution history, and the execution window. A pause or cancellation can therefore commit while calculation is stalled. Changes discovered during calculation prevent publication atomically.

In-memory databases cannot support this process boundary and are explicitly unavailable for dispatched deployment evaluation. Internal direct evaluator calls remain useful for pure infrastructure tests; production API and queued-worker dispatch supply the required job fence and use isolation.

## Evidence

- Full backend regression: **410 passed, 12 explicit native Docker skips**, 93.58 seconds. `/tmp/trademaster-deployment-process-regression.log`. One expected warning concerns the deliberately fabricated `pinned-test-model` identifier in a local SDK test.
- Final process/jobs/evaluator/guidance/failure suite: **28 passed**, 12.54 seconds. `/tmp/trademaster-deployment-process-finalfocused.log`. This covers the final monitor-connection cleanup and overlaps the broad suite.
- Real subprocess tests stop a stalled calculation on operator cancellation, kill it at its fixed deadline, and kill its supervisor to verify child termination and durable expiry recovery. A sentinel environment variable does not reach the child. Cancellation completes without waiting for the calculation's writer lock; no proposal, program or order is published. A separate test pauses during calculation and verifies atomic publication rejection.
- Existing worker tests complete one real isolated calculation and persist exactly one proposal/program without creating an order. Existing guidance entry/fill/withdrawal, revision, expiry, job recovery and API permission cases remain covered.
- Python compilation and whitespace checks pass. No UI source changed for this boundary; the preceding deployment-return acceptance records the current production build, 160 frontend checks and browser/restart evidence separately.

Later work: [deployment supervisor acceptance](QUANT_RESEARCH_DEPLOYMENT_SUPERVISOR_ACCEPTANCE.md) adds a whole-cycle boundary and health reporting to the opt-in deployment worker. The narrower calculation boundary and its original verification are recorded here.

## Remaining limits

This hard boundary covers target/risk calculation, including its artifact and database work. Broker construction, account observation and entry-cancellation orchestration still run in the calling API/worker process under their provider transport timeouts; they do not gain a whole-operation process deadline from this change. Worker availability/health reporting and provider-backed observation scheduling remain outstanding. The deployment publication lease and exact-order approval checks remain authoritative even if a provider operation stalls.

The kernel timer is a fallback if the supervisor-pipe watcher cannot run promptly; this is not a claim of instantaneous termination under every operating-system failure. No broker submission or approval path was added, no real provider was called, and the full implementation goal remains active.
