# Prospective trend evaluation and exact ticket acceptance

Verified 2026-09-04 Pacific. This is progress on slices 6–7, not completion of the implementation plan or evidence of investment returns.

## Implemented path

An active reviewed deployment can evaluate an immutable imported prospective snapshot with recorded receipt availability. Artifact and strategy hashes are checked. The same `trend_targets` function used by local replay and LEAN produces the decision; the prospective wrapper checks the declared weekly calendar, completed close plus frozen latency, available raw marks and whole long holdings. The committed capital envelope determines theoretical whole shares. Missing inputs are not converted into exits. Ticker changes fail closed pending explicit mapping reconciliation.

The saved evaluation records strategy/version, funding revision, source hash, information cutoff, accounting receipt, actual observed holdings, proposed holdings, deltas, decision covariance, code fingerprint and limitations. It creates symbol programs transactionally for changed holdings. Repeated requests for the same deployment/funding/snapshot/cutoff return the same evaluation, including equivalent timezone representations. Missing-data/unsupported-guidance evaluations persist their reason and pause entries while retaining funding; the service requests cancellation of plain outstanding entries.

Exact preparation accepts an operator-specified cent-denominated limit, never a replacement quantity. One deterministic target and one existing-boundary intent are created per evaluated instrument. Repeating preparation returns the same ticket; repricing requires a new decision rather than mutating approved terms. Exact targets can be prepared/submitted only within the saved next-session opening window (first five minutes). This is a disclosed human-execution approximation, not a promise of a next-open fill. Accepted day-limit orders can remain outstanding after the submission window; cancellation and fills retain their actual timing.

Both preparation and the final dispatch claim verify the latest evaluation, unchanged attributed shares and execution window. Planned reductions must actually fill and reconcile before any portfolio buy; a partial sale does not unlock buys. Existing account cash/buying-power/reservation/ownership/funding/cap/fee/turnover/drawdown checks apply without assuming sale proceeds. Each order retains separate exact human approval. There is no automatic approval or submission.

Quant exposes proposed portfolios, source receipts, exact ticket limits/fees/expiry/fingerprints, separate approval/submission/cancellation/reconciliation controls, and actual broker fills from the latest accounting receipt. Target program rows identify proposed targets and direct the operator to deployment controls; they do not show the legacy guessed progress percentage or nonfunctional pause/stop controls. Reload preserves saved evaluations and order/lifecycle history.

## Verification

- Combined research/accounting/execution/deployment/provider/repository/room/API suite: **322 passed, 12 explicit native Docker skips**, one expected test-model warning, 59.12 seconds. `/tmp/trademaster-evaluator-regression.log`.
- Final focused deployment/evaluation/API suite, after normalizing timezone idempotency and adding supersession coverage: **22 passed**, 4.66 seconds. `/tmp/trademaster-evaluator-focused.log`. These tests overlap the broad suite.
- Tests cover shared-kernel equality, future-price exclusion, tiny budgets producing zero shares, weekly scheduling, missing data, fixture snapshot rejection, duplicate evaluation/preparation, exact limit immutability, no implicit approval/attempt, missing-data pause, partial/complete reductions before buys, expired windows and newer evaluations rejecting older approved claims.
- The partial-sale fixture found and repaired a finite-precision cost-basis error in `FakePaperBroker`: multiply before dividing and retain the account contract's six decimal places.
- Frontend: **160 passed**, production build passes with the same four existing warnings. `/tmp/trademaster-evaluator-webtests.log`, `/tmp/trademaster-evaluator-build.log`. Python compilation and whitespace checks pass. No package dependency was added.
- Native LEAN was not rerun for this integration wrapper; its shared trend kernel is unchanged. Prior native acceptance remains separately documented.

## Browser evidence and fixture boundary

An isolated API and production frontend were seeded using the unit-test funding/evidence stub and synthetic prices/calendar. Account and snapshot metadata were deliberately shaped as prospective/broker-paper **only in the isolated test harness**. The displayed qualified gate explicitly says it is a lifecycle test. This does not demonstrate genuine promotion, a verified provider entitlement, or a remote broker connection. The production gate was not relaxed.

Actual browser actions selected the saved deployment, inspected its 48-share theoretical SIM-EQ target, entered a $100.00 limit and prepared the exact ticket with a $1 fee reserve. Separate buttons approved and submitted it to the in-memory fixture broker. The UI displayed accepted status and no fills. Pausing canceled that accepted entry and retained its $10,000 funding. After a production rebuild/reload, the paused deployment, evaluation, canceled exact order and corrected proposed-program presentation remained. No JavaScript exception or horizontal page overflow appeared. The browser did not simulate a fill; partial/full fill sequencing was exercised in the automated fixture tests.

Artifacts: `/tmp/trademaster-evaluator-ui/`, including `app.py`, `deployment.db`, `references.json`, `accepted.png` and `paused-reloaded.png`. Deployment `dep_f61a7bd4734e471c889c753a8fad5c7b`; evaluation `deval_9081b7c558bc4156a4fce095eb6d85f5`. The API loaded before the final equivalent-timezone normalization change; the focused tests cover that change. No remote broker/model call, paid data or real-money order occurred.

Final SQLite verification: one evaluation, one target, one canceled exact order and one canceled submission attempt; deployment paused with its active funding terms retained. The owned browser, API and web server were stopped and their listening ports verified clear.

## Remaining work

The later [guidance deployment acceptance](QUANT_RESEARCH_GUIDANCE_DEPLOYMENT_ACCEPTANCE.md) implements consumed notices, actual-fill holding clocks, withdrawal cancellation and operational failure/review recovery. Genuine ingestion and provider provenance/entitlements are not established by imported declarations. Operational exceptions now have durable failure/review recovery; process crash and startup scheduling still require implementation. Fractional/external holdings and source changes must retain explicit accounting and review constraints. Stable-instrument ticker changes remain blocked. The nominal funding envelope is not yet a deployment equity/return account, and decision covariance is not recalculated from rounded actual exposures. Detailed human-delay/rejection attribution, corrected-source/protective-child accounting, the genuine positive promotion and complete release/provider walkthrough remain open. The full goal is active.
