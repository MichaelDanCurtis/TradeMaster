# Protective-order accounting acceptance

Verified 2026-09-05. Synthetic software acceptance and a local HTTP protocol test; no remote broker order or investment claim.

## Behavior

Account observations now preserve typed parent/child order families inside the existing immutable reconciliation request. The native adapter uses a read-only order-ID lookup with `nested=true`, including completed entry parents. Alpaca documents nested child orders in its [order guide](https://docs.alpaca.markets/us/docs/orders-at-alpaca) and the single-order nested option in [GetOrderByIdRequest](https://alpaca.markets/sdks/python/api_reference/trading/requests.html).

The service reads known protected parents even when their entry attempt is terminal. It checks the account again after the reads. The current observation is bounded to 100 protected parents; larger histories fail explicitly. This is a declared capacity limit, not proof of long-history readiness.

Repository validation binds each family to the account's submitted exact order and client ID. Child roles, symbol, side, quantity and unique identities are checked. Historical family receipts retain lineage when later observations change child IDs. A child cannot be claimed by incompatible parents. Missing current family coverage, missing roles after a parent fill, changed protective prices or inconsistent fill identity prevent a reconciled return claim. Unknown order statuses remain unknown. No status lookup submits, replaces or cancels an order.

Accounting assigns the child executor to the parent order's manual or deployment identity. FIFO continues to assign sale proceeds, realized P&L and fees to the actual lots consumed. An external/manual lot can therefore be sold by a deployment's protective order without relabelling the lot's ownership. Native cumulative order quantities are descriptive; only activity fills move ledger cash or shares. Child fills are not added to the original entry quantity or its execution-price comparison.

Performance shows child status, role, filled/unfilled quantities, prices, observation time and parent attribution. Pending cancellation remains pending. The observed-fill table labels protective executions, and deployment execution history has a separate protective-exit section when reconciled linked fills exist. Current child observations can follow the account valuation; the UI states that timing distinction.

## Verification

- Focused accounting, lineage, native HTTP and execution-attribution suite: **38 passed**, `/tmp/trademaster-protection-focused.log`.
- Broad research/API/broker/repository regression: **436 passed, 12 explicit native integration skips**, one existing pinned-test-model warning, `/tmp/trademaster-protection-regression.log`.
- Frontend: **160 passed**, `/tmp/trademaster-protection-webtests.log`. Production build passed with four existing unrelated warnings, `/tmp/trademaster-protection-webbuild.log`.

New cases cover a completed parent's child fill, restart/idempotency, missing lineage followed by recovery, changed prices, a foreign parent client ID, wrong-side/symbol/oversized/repeated child identities, an incompatible child fill, partial fill with pending cancellation, and FIFO ownership across legacy and deployment lots. The local HTTP test verifies the actual GET query and absence of POST/DELETE calls. It rejects a foreign-symbol child returned by the protocol fixture. Native LEAN was not rerun for this broker/accounting-only change; earlier paired-event LEAN acceptance remains separate.

The isolated browser database `/tmp/trademaster-protection-ui/research.db` uses a reviewed synthetic USD 1,000 baseline, a two-share entry at USD 100, one protective sale at USD 110, one remaining share marked at USD 110, and two USD 1 fees. Cash is USD 908, equity USD 1,018 and period P&L USD 18. The take-profit child remains `pending_cancel` with one filled and one unfilled share; the observed stop is `new` for the remaining share.

Browser acceptance inspected the Performance protection and fill tables, keyboard history access, page reload and API restart against the same database. No JavaScript exceptions, alerts or page-width overflow appeared. Screenshot `/tmp/trademaster-protection-ui/protection.png` was visually inspected. Account `90fe46839df22ccdf2f33a9a62c62a522ed7364464b536f8b4462e5ef3c43afe`, receipt `par_f2f9d44da4744a408c7f27225c88a814`. The browser and test API/web servers were stopped afterward.

## Remaining requirements

Provider-specific replacement/correction semantics, source-revision resolution and history capacity remain unfinished. Incompatible or incomplete native protection responses fail explicitly rather than fabricating protection. The current deterministic deployment target API creates plain limits; this work does not introduce new strategy-level protective-order authority. The browser case verifies manual parent lineage in Performance; a genuine funded deployment/protection release walkthrough remains separate. Genuine research data, positive eligible promotion, provider-backed prospective scheduling and full release acceptance are still outstanding.
