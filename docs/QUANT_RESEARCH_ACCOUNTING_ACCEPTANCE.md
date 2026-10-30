# Paper account accounting acceptance

Verified 2026-09-04 Pacific. This is a software milestone within the unfinished [build plan](QUANT_RESEARCH_BUILD_PLAN.md), not evidence of profitable trading or real-provider readiness.

## Implemented boundary

Performance now reads persisted observations rather than constructing historical outcomes from current positions. An operator reviews and approves the exact opening account snapshot before observation starts. This permanent baseline excludes earlier returns and cannot reset an account's history. Source activity IDs, original payloads, conflicting economic revisions and every reconciliation receipt are retained. Numeric formatting and retrieval metadata changes alone do not create economic revisions.

The Decimal kernel reconciles cash, quantities, marked equity and investment P&L independently. FIFO analytical lot ownership separates opening/manual/external/deployment fills, with opening unrealized gains excluded from period P&L. Hand-calculated cases cover splits, fractional-share cash compensation, symbol changes, dividends, interest, standalone fees, partial sales and manual exits. Analytical FIFO basis is distinct from broker/tax basis. Unattributed income remains explicit.

External deposits and withdrawals are separated from dollar investment P&L. Exact time-weighted returns geometrically link subperiods using supplied contemporaneous flow valuations; absent or unordered flow valuations leave return and drawdown unavailable. Observed zero equity reports a total loss and 100% drawdown. Observed peaks do not imply coverage of unobserved intraday highs. This follows the valuation requirement described in the [GIPS asset-owner handbook](https://www.gipsstandards.org/standards/gips-standards-for-asset-owners/gips-standards-handbook-for-asset-owners/); no GIPS compliance claim is made.

The broker wrapper supplies drawdown only from reconciled observations. Missing evidence blocks new entries through the existing exact-order boundary while funded reductions remain reviewable. Reconciliation looks up unknown submissions and current orders by client ID; it never posts a new order. The separate worker supports bounded observation cycles and `--once`; it is not automatically started.

## Verification

- Final research/broker/provider/repository/room regression: **222 passed, 12 explicitly skipped native Docker cases**, one expected test-model warning, 39.40 seconds. Log: `/tmp/trademaster-accounting-final-regression.log`. Native LEAN was verified in the prior [LEAN acceptance](QUANT_RESEARCH_LEAN_ACCEPTANCE.md) and was not rerun for this accounting milestone.
- API/accounting/actual-HTTP execution subset: **22 passed** before the final discrepancy-display preservation fix. The final full suite includes that fix and its regression assertion. Earlier accounting/UI integration: **148 passed**; suites overlap.
- Web tests: **160 passed**, `/tmp/trademaster-accounting-webtests.log`. Production build passes, `/tmp/trademaster-accounting-build.log`, with the same four existing warnings documented in implementation status.
- Actual requests transport fixture: server accepts an order then drops its response; worker reconnect recovers the accepted order with one economic order and one POST. Source parsing preserves native fill IDs/timestamps, signed cash activities and unknown records.
- CLI smoke in an empty isolated database with an empty environment returned `baseline_review_required` without order submission.

## Browser acceptance

The production frontend and an isolated API with an explicitly labelled `FakePaperBroker` completed opening-baseline review, approval, initial reconciliation, exact manual order review/approval, accepted order, fixture fill, mark change and reconciliation. The temporary fixture-control endpoints existed only in `/tmp/trademaster-accounting-ui/acceptance_app.py`.

One NVDA share filled at $900 and was marked at $950. Performance showed $100,050 equity, $50 investment P&L and 0.05% time-weighted return. A subsequent $100 deposit without contemporaneous flow valuation produced $100,150 equity, **the same $50 investment P&L**, $100 net external flow and unavailable return/drawdown. Reload preserved these values, one fill and the observed equity chart. Preparing another entry displayed the missing-drawdown reason and created no second intent or order. No JavaScript exception or horizontal page overflow appeared.

Database `/tmp/trademaster-accounting-ui/ui.db` contains one baseline, six immutable reconciliation receipts, two activities and one exact order/attempt. Baseline `pab_a6d3e09aedfd4bf4ae47f8f6233d21bc`; latest receipt `par_faa0b83155344140b6b604929a81ee3d`; intent `ti_8660c5283e5648c18dcf1457d825158c`; exact order `po_b7a570866cd04aa78b1033c139bf1697`; fingerprint `a74c4d78499da602cb5153e6b697398d5a256ba5c28da357643cfc68952b39ba`. Screenshots include `reconciled-pnl.png`, `deposit-not-profit.png`, `reloaded-performance.png`, and `blocked-entry.png` in that directory. The browser and owned API/web servers were stopped afterward.

The browser API loaded before later calculation-build fingerprint, economic-format normalization and discrepancy-display fixes; those backend changes were verified by the final test suite. Do not treat older browser receipts as containing the new build field.

## Remaining limitations

The Alpaca reader preserves unknown actions and day-only timestamps. It does not invent a split ratio, fee, posting instant, dividend ownership date or cash-flow valuation. Alpaca documents different timing for fills and non-trade activities and creation-time pagination filters in its [activity reference](https://docs.alpaca.markets/us/reference/getaccountactivitiesbyactivitytype-1) and [activity guide](https://docs.alpaca.markets/us/docs/account-activities). Corporate-action mappings, corrections, actual fee semantics and provider coverage require further verification. Date-only activity or asynchronous marks may correctly prevent reconciliation. The account snapshot reader's $1 mark tolerance does not relax the ledger's stricter identity checks.

Material source corrections remain preserved and blocking; a reviewed correction-resolution workflow is not yet implemented. Protective child order attribution, deployment capital accounting and links from performance to exact strategy versions remain unfinished. Full cumulative recomputation/report retention has not been validated for production history volume. The provider-backed smoke requires a configured account and human order approval; no remote broker/model calls or paid purchases occurred here.

Run the observer explicitly from the repository root:

```sh
.venv/bin/python -m tradingagents.research.accounting_worker --database-url sqlite:////absolute/path/ui.db --once
```

Omit `--once` for repeated cycles; `--interval-seconds` accepts 15 through 86400. Review the baseline in Portfolio → Performance first. Fixture accounts remain visibly synthetic.
