# Paper execution scheduler

Implemented September 5, 2026. Quant now has an execution scheduler for **TWAP** and **Dollar-cost rungs (DCA)**. These use the existing exact-order approval, risk, reservation, reconciliation, and accounting mechanisms. The other catalog algorithms remain analytical previews.

## Review and execution

1. Select TWAP or Dollar-cost rungs in Quant. Set the symbol, side, budget, and manual reference price. That reference becomes a limit, not a market quote.
2. Set 2–12 slices/rungs, a 1–390 minute duration, and a future start. DCA also uses a ladder span.
3. Prepare the schedule. Review every whole-share quantity, rounded price limit, release time, deadline, account, maximum order notional, and unused budget. Clear manual protective inputs first; scheduled orders do not attach stop-loss or take-profit children.
4. Explicitly approve the listed orders before the review expires. Preparing a schedule sends no orders. Approval applies only to the immutable listed children.
5. The worker submits due children through the same durable exact-order boundary as manual paper orders. It checks fresh account risk, outstanding commitments, holdings, and deployment allocations again before each submission.

TWAP uses fixed-limit orders in evenly spaced wall-clock windows. A slice expires when the next slice is due; the final slice expires at the schedule end. DCA releases all reviewed limits at the start and leaves them resting until the end. Unused whole-share budget is displayed and never silently redistributed. No repricing, market-order fallback, short selling, leverage, or catch-up burst is added.

Broker schedules now require a fresh Alpaca regular-session calendar and clock. Preparation, approval/resume, and each new dispatch validate the session; every deadline must be at least 60 seconds before its close. Holidays and closed hours are rejected, not shifted forward. Preparation supports starts up to seven days ahead with a five-minute approval review. The UI exposes native upcoming sessions and an exact local start-time input. Fixture schedules remain explicitly labelled and do not establish exchange-calendar evidence. A valid schedule does not guarantee broker acceptance, a fill, or income.

## Controls and recovery

- **Pause** blocks new claims. Existing broker orders may still fill; their original deadlines remain in force.
- **Resume** keeps the original terms and timing. Missed windows are canceled locally rather than submitted late.
- **Stop** atomically revokes unsubmitted children and requests cancellation of outstanding broker orders. Reservations remain until a broker receipt confirms a terminal outcome. A POST claimed before Pause or Stop may still reach the broker and must then be reconciled/canceled.
- An uncertain submission pauses further dispatch. Recovery queries the durable client order ID; it never retries the order POST. An order that cannot be found after a crash remains uncertain instead of becoming a duplicate submission.
- Stalled cycles are bounded and killed. The schedule pauses; durable claims survive the process. Multiple workers cannot claim the same child twice.
- Schedule terms, leg linkage, approval records, and event history are immutable. UI actions require the current review hash and revision. The manual order endpoint cannot bypass schedule approval, pause, start time, or deadline.
- Performance accounting attributes broker-observed scheduled fills to their schedule. A submitted order with zero observed fills remains zero filled.

**Keep the computer and scheduler worker running.** Broker orders are GTC: they can remain working during host sleep, worker failure, or a network outage. Local deadlines request cancellation when the worker can reach the broker; they are not broker-native expiration instructions. Restart resumes reconciliation and cancels expired work without submitting missed slices.

## Local service

`npm run dev:local` starts API, web, research, deployment evaluation, and scheduler tmux sessions. It verifies API-visible worker heartbeats. `npm run stop:local` stops all five.

The scheduler session is `trademaster-scheduler`; its command is:

```bash
.venv/bin/python -m tradingagents.scheduling.worker --database-url sqlite:////absolute/path/to/.tradingagents-ui.db
```

`GET /api/execution-schedules/runtime` reports recent heartbeats and executable capabilities. Scheduler routes require the market room. A heartbeat establishes worker connectivity, not broker health or permission to trade. No model API is used by the scheduler. Production routing uses the configured Alpaca **paper** broker and reconciled account data.

## Verification

Backend coverage includes due-time gating, approval and risk changes, DCA prices and budget rounding, skipped windows, pause/resume/stop, concurrent workers, lost submission replies, crash recovery, delayed cancellation, account attribution, immutable terms, API permissions, order-list status, process startup, and timeout cleanup.

Browser verification uses a separate SQLite database and fixture broker with external provider transport disabled. The walkthrough covers preparation, explicit approval, pause/resume, timed acceptance, Stop, cancellation receipts, persisted history, and unsupported algorithm messaging. This verifies local execution behavior; it does not establish actual Alpaca order acceptance or fills. No orders were submitted to the user's Alpaca account during this work.

Final results: **451 backend tests passed**, including 18 scheduler tests; **160 frontend tests passed**; Next.js production build and shell syntax checks passed. The normal startup reported all three worker heartbeats. Browser verification finished with two stopped schedules, six canceled children, and one canceled fixture submission. Normal account records remained unchanged: zero schedules, zero exact execution attempts, and the same 12 legacy broker-order records. The normal account still requires its explicit baseline review before new entries can pass reconciled-account risk checks.

Calendar validation acceptance and current trial terms: [five-session paper goal](PAPER_TRIAL_GOAL.md). Existing legacy schedules without a verified session pin must be prepared again before approval, resume, or new broker dispatch; cancellation/reconciliation stays available.
