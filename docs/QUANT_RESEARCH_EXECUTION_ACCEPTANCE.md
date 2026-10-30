# Exact paper execution acceptance

Date: 2026-09-04 (Pacific). This is progress on slices 6–7, not completion of the implementation plan or broker-paper readiness.

## Implemented boundary

`research/execution_contracts.py`, `execution_models.py`, `execution_repository.py` and `execution_service.py` add immutable exact order/policy/account pins, durable attempts, remaining-share/cash reservations and append-only execution events. Existing trade intents, broker-order records and the approval ledger remain the integration surface. Tables are additive.

A preview freezes whole-share quantity, USD limit price, protective prices, fee reserve, duration, expiry, account identity and policy. Approval records that fingerprint. Immediately before dispatch a fresh account read and transactional claim recheck approval, expiry, current holdings, buying power, cash reserve, total exposure, position/group concentration, daily turnover and drawdown. Unknown group exposure is conservatively included. Missing drawdown blocks new buys; a funded, approved reduction remains possible.

Manual orders share account reservations. The account writer and stable client order ID are committed before the POST. A previously claimed order cannot POST again: retries reconcile by client ID. Lost responses, supervisor interruptions and missing broker lookups remain unknown, retaining reservations. A partial fill reduces the remaining quantity. Cancellation acknowledgement over HTTP does not release a reservation; broker order status must confirm it. Further partial fills preserve the pending cancellation state. Observations cannot lower cumulative fills or silently substitute a different broker order ID.

The Alpaca adapter sends the frozen quantity and limit directly, without another quote or sizing pass. It has separate lookup/cancellation methods, binds credentials within the adapter instance, disables redirects for these methods, and rejects live/unverified production endpoints. Explicit local test endpoints are labelled fixtures. Current account snapshots read account/positions/open orders twice to detect economic changes and page execution activities for daily turnover. Short/non-equity positions, incomplete pages, inconsistent equity or changing account contents fail closed. Broker reads remain sequential, not an atomic exchange snapshot.

The wire behavior follows the official [Alpaca order API](https://docs.alpaca.markets/us/docs/orders-at-alpaca), including client-ID lookup, and [account activity pagination](https://docs.alpaca.markets/us/reference/getaccountactivitiesbyactivitytype-1). Trading-day turnover uses execution activity timestamps in the New York trading day, not order creation timestamps. These docs establish API semantics; the tests below use localhost, not a remote brokerage account.

## Product changes

Quant now prepares a reviewable exact ticket before human approval. The previous workbench chain created and immediately approved a fresh preview without displaying its terms; that chain is removed. The pending-order ladder opens the same exact ticket and includes unknown, partial-fill and cancellation states. Approval includes the displayed fingerprint. Saved history and explicit reconciliation endpoints support refresh/recovery. The fixture account persists across requests within an app instance, allowing real reconciliation of its simulated order state.

The ticket distinguishes fixture simulation from broker-paper evidence, shows account/quantity/limit/deadline/protective prices, and explains whether funds remain reserved. The workbench no longer displays hardcoded account-risk slack. It explicitly describes its algorithm preview as analytical: this manual ticket does not execute a selected multi-leg algorithm or schedule. Deployment-to-program integration remains required.

A provider-default seeding race surfaced during API tests. SQLite default insertion now tolerates concurrent initialization without overwriting existing configuration; a forced simultaneous-read regression covers it. Two older API tests were corrected to explicitly request simulated execution and use the existing `runs` response envelope, rather than assuming synchronous real execution or a bare list.

## Verification

- `tests/research/test_execution.py`: exact identity, stale snapshots, approval revocation, capital changes, competing claims, pending reservations, partial fills, unconfirmed cancellation, unknown responses, process/repository restart, external holdings, missing drawdown and reduction behavior.
- `tests/research/test_execution_alpaca.py`: real `requests` transport against an independent localhost HTTP broker. A server accepts an order and closes the connection without a response; a restarted service reconciles it repeatedly with exactly **one economic order and one POST**. Separate cases verify exact wire terms, cancellation acknowledgement without cancellation, missing drawdown, changing accounts and rejected live endpoints.
- Full execution/broker/UI API/repository regression: **142 passed**, `/tmp/trademaster-exact-release-regression.log`.
- Research/provider regression: **164 passed, 12 explicit Docker skips**, `/tmp/trademaster-exact-research-regression.log`. Subsequent targeted execution/repository/wire checks: **50 passed**, including the new concurrent-provider and pending-cancel tests, `/tmp/trademaster-exact-final-checks.log`.
- Full frontend source-contract suite: **160 passed**, `/tmp/trademaster-exact-webtests.log`. Production build passed with the same four existing warnings, `/tmp/trademaster-exact-build.log`.
- Python compilation and `git diff --check` passed.

Production-browser acceptance used an isolated credential-free API database `/tmp/trademaster-exact-ui/ui.db` and the built web app. Keyboard operation prepared a one-share NVDA fixture limit order at $900 from a $1,000 budget, displayed its terms before approval, and received fixture acceptance. After a page reload, Quant's pending ladder reopened the same saved ticket. Explicit reconciliation retained the original broker ID, and cancellation confirmed the final `canceled` status. No page exception, framework overlay or horizontal page overflow was observed. The browser and both owned acceptance servers were stopped afterwards.

- Intent: `ti_c1f27cbc72d24d5b9a5e43b145d4110f`
- Exact order: `po_1dab02e63fc0456082d25746c99e69c3`
- Fingerprint: `8df98af618e5c6ce45f400e59da1d578191bfdda3d3e733861e110d17e27c4ed`
- Saved result: one attempt, six immutable events, one fixture economic order, canceled with no fill.
- Screenshots: `/tmp/trademaster-exact-ui/initial.png`, `exact-preview.png`, `recovered-canceled.png`.

## Explicitly incomplete

The configured Alpaca path does **not yet have a reconciled drawdown provider**. It returns unknown drawdown and blocks new entries, rather than substituting zero or treating daily P&L as drawdown. The injected zero in localhost tests is explicitly fixture-only. Real broker fee assumptions, coverage and account baselines still need verification.

Persisted cash flows, equity snapshots, activity reconciliation, strategy attribution and the Performance UI remain to be implemented. Deployment lifecycle, funding envelopes, theoretical/approved targets, program joins, pause/resume review and promotion UI are also outstanding. Reservations and nullable deployment/target IDs are foundations, not proof those paths exist. Unfavorable broker discrepancies and protective-child attribution need further accounting coverage. The real-account smoke requires configured credentials and an explicit human order approval; none was attempted. No remote broker order, paid data purchase or live-money action occurred.

The goal remains the full build plan. These verified manual-order and recovery paths do not establish strategy profitability, deployability or release completion.
