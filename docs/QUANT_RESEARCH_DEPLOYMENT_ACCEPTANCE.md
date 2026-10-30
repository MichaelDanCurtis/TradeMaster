# Paper deployment review and lifecycle acceptance

Verified 2026-09-04 Pacific. This implements the review/funding/lifecycle boundary in the [build plan](QUANT_RESEARCH_BUILD_PLAN.md). The full plan is still active. The subsequent [evaluator acceptance](QUANT_RESEARCH_EVALUATOR_ACCEPTANCE.md) adds prospective trend targets, symbol programs and exact ticket preparation. Guidance and the complete genuine funded execution walkthrough remain open.

## Implemented

Research can hand a selected experiment/version to Quant and create a draft funding proposal. The backend pins the immutable strategy version, experiment, account identity and request idempotency key. Each funding revision is a separate immutable record. Proposed capital grants no allocation until a human approves a qualifying review. Execution limits cannot loosen the frozen strategy's position/group/turnover/drawdown limits or lower its cash reserve. Fee reserve, fee source and funding rationale are explicit.

A promotion review retains its exact terms, evidence hash, version hash, account economics, accounting receipt, funding calculation, individual gates and five-minute expiration. It checks the selected version's eligibility, genuine holdout and availability, reference inclusion, report integrity/provenance, actual paper-account evidence, observed drawdown and current funding capacity. Fixture/development/unverified/ineligible evidence cannot activate a deployment. Human rejection, revision and deferral are persisted without rewriting the original review. Research has request/read grants but no lifecycle-management grant.

Activation and resume require the displayed review fingerprint and revision. Account economics changing after review require a fresh review. Competing activations recheck funding under SQLite's account transaction. Funding includes other committed envelopes, exposure above those envelopes, manual/unallocated holdings, pending buys and retained fees. Unconfirmed sales never fund an allocation. Paused/reviewed deployments retain their existing committed envelope; a capital amendment remains a proposal until renewed approval. A new activation and a resume are distinct actions.

The shared exact-order preview and dispatch claim check deployment state, account, active funding revision, immutable target, policy, universe/group, fee reserve, owned shares, capital reserve, concentration and turnover. A database uniqueness index and transactional lookup allow at most one exact ticket per target. A paused deployment cannot use an older approved buy ticket. Funded reductions remain reviewable. Manual buys cannot spend committed deployment capital. Shared/manual ownership of a strategy's symbol requires explicit allocation resolution rather than silently consuming another owner's lots.

Pause commits before broker construction or transport. It then requests cancellation of plain unfilled entry orders, retaining reservations until acknowledgment. It does not liquidate positions. Automatic cancellation of protective entry parents is withheld because it could affect protective exits; that case requires review. The supported strategy target boundary currently permits plain limit orders, consistent with the initial frozen templates. Retirement requires fresh reconciled balances, no attributed holdings, no outstanding local orders and no native open orders in the strategy universe. Retirement does not sell holdings, reset performance or erase history.

Additive tables cover deployment identity, funding terms, promotion reviews, lifecycle events, evaluation/target records and program links. SQLite guards prevent changing/deleting immutable evidence and deployment identity. These tables were foundations at this lifecycle checkpoint. The subsequent trend evaluator now populates evaluations, targets and program links through production code; see the separate evaluator acceptance record.

## Verification

- Final research, deployment, accounting, execution, provider, repository, room-policy and UI API suite: **315 passed, 12 explicit native Docker skips**, one expected test-model warning, 59.77 seconds. `/tmp/trademaster-deployment-final-regression.log`.
- Focused deployment/API/execution suite: **38 passed** before the final target uniqueness assertion; the full suite includes that assertion and later changes. An earlier API/UI subset passed **82** checks. These figures overlap and are not additive.
- Positive lifecycle tests use explicitly synthetic protocol-shaped account observations and a stubbed qualified-evidence assessment. They verify activation/funding infrastructure, **not genuine research eligibility or remote broker readiness**. Unstubbed tests verify real fixture reports cannot activate; API tests verify Research cannot promote, pause or loosen authority.
- Tests cover concurrent allocations, changed buying power, wrong review hash, immutable identity/history, capital amendment/resume, pause followed by an old approved claim, unacknowledged cancellation, adapter-construction failure during pause, manual spending of committed capital, exposure above another envelope, retained holdings preventing retirement, paused reductions, risk-limit amendments and repeated target preparation.
- Frontend tests and production build pass. Four existing warnings remain in ActiveProgramsTable, AlgorithmCatalogueRail, BriefWorkspace and SettingsDrawer. Logs: `/tmp/trademaster-deployment-webtests.log` and `/tmp/trademaster-deployment-build.log`. TypeScript build found and fixed a missing callback between the strategy editor and its evidence panel. No new package dependency.
- Native LEAN was not rerun for lifecycle-only code; prior actual native/local decision/account parity is documented in [covariance acceptance](QUANT_RESEARCH_COVARIANCE_ACCEPTANCE.md).

## Browser walkthrough

An isolated production frontend/API completed these actual UI actions:

1. Reviewed and approved a visibly synthetic $100,000 cash opening baseline.
2. Opened the completed synthetic research experiment and selected “Review variant 1 in Quant.” The correct experiment/version arrived preselected.
3. Saved a $10,000 draft envelope with a $1 fixture fee reserve and explicit rationale.
4. Prepared the current review. The UI displayed the exact account/equity/funding and failed genuine-evidence/reference/account gates. The activation button was disabled; no funding was committed.
5. Rejected the review, proposed a $12,000 envelope and reloaded. The new proposed amount and the original rejected $10,000 review both persisted.
6. Retired the proposal after reconciliation. No exact order or execution attempt was created.

No application JavaScript exception or horizontal page overflow appeared. Screenshots and the SQLite database are in `/tmp/trademaster-deployment-ui/`: `fixture-review.png`, `reloaded-amendment.png`, `retired.png`. The API loaded before the final target-uniqueness change; no target was prepared in this negative-evidence browser flow, and the final test suite verifies that later guard.

Deployment `dep_a632e50329a74f288013bd4a1a0c8cff`, version `sv_d6eaad8efe434928b8731d6e70cd16aa`, experiment `exp_b8f704dab07e4e648119ea988e196ae4`. Review `prv_fe8e8b8a20ce46af8d7aec482e56e135`, hash `23769d61ea5d42c5576d7a91ab15ebadd3d9123ac94517891b48b374beea78af`. Final database state: retired, revision 5, no active funding, two immutable terms, one review, five lifecycle events, zero exact orders/attempts. Owned acceptance browser and API/web processes were stopped. No remote model/broker call or paid purchase occurred.

## Still required

Complete the remaining prospective guidance evaluator and dated source ingestion, detailed target/approval/actual-fill attribution and startup recovery. The later trend evaluator implements theoretical targets, serial sell-before-buy sequencing, idempotent program/target creation and the review/ticket flow. Wire failed-evaluation lifecycle handling and strategy-version-linked accounting/performance. Verify eligible positive promotion using genuine qualified evidence rather than an infrastructure stub. Provider entitlement, timestamp/corporate-action/fee semantics, protective-child attribution, corrected-source resolution and the conditional provider-backed smoke remain open. The active goal is not complete.
