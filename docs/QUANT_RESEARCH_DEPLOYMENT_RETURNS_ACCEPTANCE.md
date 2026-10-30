# Deployment capital and return accounting acceptance

Verified 2026-09-05. This record covers software behavior with isolated synthetic inputs. It is not investment evidence or a genuine broker-paper result.

## Implemented behavior

Each newly funded deployment has an immutable internal capital ledger tied to its account, frozen strategy version, funding terms, exact human review, reconciliation, actor and lifecycle revision. This allocation is analytical ownership within the paper account, not a broker deposit. Nominal execution envelopes remain separate from measured book equity.

An explicit funding revision transfers the difference between the reviewed target capital and current deployment equity. A normal pause/resume retains its capital and earned P&L without resetting returns. Releases require attributed cash; unsold holdings cannot finance a release. Retirement releases the remaining cash after positions and outstanding orders clear. Retained gains are reserved against competing deployment/manual spending, and entry checks require the deployment's attributed cash rather than unrelated account cash.

The reconciled FIFO ledger now retains owner cash movements and owned-position valuation history. Principal, realized/unrealized P&L, entitled dividends, fees, splits and cash compensation follow actual lot ownership, including an external manual sale of deployment shares. External account deposits stay unallocated; unattributed interest and fees remain separate. Owner cash sums independently reconcile to account cash.

Performance displays deployment cash, market value, equity, investment P&L, time-weighted return, observed drawdown, allocation history and calculation provenance. Unitization requires an exact pre-flow valuation when positions are held. A prior fresh quote is not a price at the approval instant, and a day-only activity timestamp cannot establish intraday precision. Missing flow marks preserve reconciled dollar P&L and equity while making chained return/drawdown unavailable. Cash-only flows require no estimated market price. Pending allocations remain visible without being backdated into older account observations. Zero equity can correctly report a total loss; undefined or discrepant cases remain explicit.

Old reports without owner histories and legacy deployments without an allocation baseline do not receive invented performance. A legacy deployment can still retire through its existing lifecycle rules. Current immutable calculation inputs include source report hashes, allocation hashes and the loaded implementation build.

## Verification

- Broad backend regression: **402 passed, 12 explicit native Docker skips**, before the final timestamp-precision and pending-allocation cases. Log: `/tmp/trademaster-deployment-returns-regression.log`.
- Final accounting, deployment, evaluator and execution checks: **67 passed** after those additions. Log: `/tmp/trademaster-deployment-returns-finalfocused.log`.
- Frontend suite: **160 passed**. Production build passed after the selector styling change, with the four existing nonfatal warnings recorded in the implementation status. Logs: `/tmp/trademaster-deployment-returns-webtests.log` and `/tmp/trademaster-deployment-returns-webbuild.log`.
- Pure hand-calculated cases cover ownership partition, manual FIFO exits, income/fees/actions, outside deposits, funding increases/releases, missing valuations, date-only events, total loss, pending observations and unavailable legacy/discrepant history. Lifecycle tests cover immutable allocations, normal resume, explicit rebasing, retirement, retained-profit reservations and cash-deficit entry rejection.
- Production browser acceptance inspected the exact funding review, both return states, history controls, and persisted values after reopening the same database without reseeding or approving anything. No JavaScript errors or horizontal page overflow appeared. Screenshots are in `/tmp/trademaster-deployment-returns-ui-final/`.

The cash-only fixture earned $100, released $100 through a new funding review, and retained $10,000 equity, $100 investment P&L and a 1% return after restart. The held-position fixture increased capital to $25,000 and retained $23,900 cash, $1,100 positions and $100 P&L; its exact return and drawdown remained unavailable because no price existed at the funding instant. The review displayed $20,100 pre-flow equity, $19,000 cash and a $4,900 allocation.

Positive promotion/account metadata in this isolated harness were deliberately stubbed. No real broker, model provider, paid data, external deposit or genuine funded strategy was used. Test API/web servers and the browser were stopped after verification.

## Remaining release scope

Provider-specific activity semantics, protective-child attribution, corrected-source reconciliation, history capacity and genuine provider acceptance remain separate work. Drawdown here is sampled at saved valuations, not a guarantee about unobserved intraday losses. The complete release walkthrough and other outstanding plan requirements remain active.
