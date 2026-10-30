# Proposal, approval and fill attribution acceptance

Verified 2026-09-05. This implements execution-history attribution for the paper deployment path. It does not establish profitable research, causal delay costs, deployment returns or real-provider readiness.

## Implemented

`execution_attribution.py` reads a coherent database snapshot and joins each immutable evaluation/proposal to its exact target, order, approvals, durable dispatch attempt, execution events and the latest identified accounting receipt. It makes no broker calls or mutations. Pages contain 1–25 evaluations (default 10), with a checked deployment-specific cursor for older history. Empty/no-signal evaluations remain visible.

The report distinguishes desired holdings/delta, prepared quantity, historically approved quantity, the exact approval used by dispatch, broker-reported fill quantity, and reconciled activity quantity. It retains decision/evaluation/window/preparation/approval/dispatch/response/cancellation/fill times, elapsed intervals, and recorded event actors. A dispatch claim is not labeled proof of remote submission; response times are local observations. Missing or reversed clock intervals remain unavailable. Fill chronology compares timezone-aware instants rather than ISO strings.

Outcomes distinguish no prepared ticket, elapsed or superseded opportunity, approval wait/revocation, pre-dispatch cancellation, unresolved submission, pending fill reconciliation, unacknowledged cancellation, partial/open execution and terminal filled/canceled/expired/rejected states. Old evaluations remain evidence rather than being rewritten by a later target.

Filled-share reference differences use `side × sum(quantity × (fill_price − decision_reference))`; positive is adverse for buys or sells. Recorded fees attached to those fills are shown separately and in the combined difference. This is not realized P&L, causal delay cost, all account fees, or hypothetical profit on unfilled shares. Repeated evaluations cannot be summed into a return. Unreconciled account receipts do not publish confirmed fill costs/completion.

Exact-order approval rows now have SQLite update/delete guards scoped to linked exact-paper intents. Revocation/cancellation remains a new approval/event, preserving historical approvals. New approval events include the exact approval ID. Legacy approval rows outside exact paper execution are unaffected.

Read-only views are available in Quant and Portfolio → Performance. The account route checks account/deployment ownership. UI requests abort on selection/unmount and have explicit loading/error/empty states, chronological details, sources and older-page navigation. Refresh/reload preserves authoritative history.

## Verification

Broad backend suite: **364 passed, 12 explicit native integration skips**, 69.98 seconds, `/tmp/trademaster-execution-attribution-regression.log`:

```sh
.venv/bin/python -m pytest tests/research tests/ui/test_api.py tests/ui/test_broker_service.py tests/ui/test_alpaca_broker.py tests/ui/test_repository.py tests/ui/test_room_policy.py tests/test_role_models.py -q
```

Later focused execution-attribution/execution/evaluator/jobs checks passed **44 tests** in 6.96 seconds, covering the final pending-cancellation and timezone-ordering changes. Log: `/tmp/trademaster-execution-attribution-focused.log`. These overlap the broad suite. The native LEAN suite was not rerun.

Tests independently verify buy and sell adverse reference differences, first versus dispatch-used approval timing, three filled versus seven unfilled shares after cancellation, missing reconciliation, unresolved submission, unacknowledged cancellation, zero/negative clock intervals, mixed timezones, approval immutability, read-only account routing, foreign-account/cursor rejection, pagination, and broker acknowledgment preceding matched account activity.

Frontend **160 passed**, `/tmp/trademaster-execution-attribution-webtests.log`. Final production build passed, `/tmp/trademaster-execution-attribution-build.log`, retaining four existing unrelated warnings.

Browser acceptance initially exposed React hydration error 418 when midnight changed the header date from the build-time date. The header date and portfolio session clock now start with deterministic placeholders and initialize/update after mounting, avoiding a stale prerendered clock. Rebuilt/reloaded browser sessions had no JavaScript errors, framework overlay, execution-history alert or horizontal page overflow.

The isolated harness `/tmp/trademaster-execution-attribution-ui` prepared/approved 48 synthetic shares, filled 3 at $100, canceled the balance, and reconciled the account. Both Quant and Performance displayed 48 historically/dispatch approved, 3 reconciled filled, and 45 unfilled shares. Timing details showed the saved events and an approximately −$8.0367 filled-share difference against the pinned $102.6789 decision reference, explicitly separate from P&L. Reload preserved the report. Keyboard focus/Enter operated navigation and disclosure panels.

Deployment: `dep_6efb37abc92645a6b287a75c41ceb2c3`. Screenshots: `rebuilt.png`, `performance.png`, `timeline.png`, `quant.png`; source report: `references.json` in that directory. The harness stubs qualified research evidence and fabricates broker-paper/prospective metadata around synthetic data. It proves protocol behavior only. No remote model/provider call, real order, purchase or commit occurred. Test browser and servers were stopped afterward.

## Remaining release work

Deployment capital/equity and flow-adjusted returns remain unfinished. So do strategy-design assistance, genuine/labelled/paired-event acceptance, provider verification and the other operational/accounting items in the implementation status. Execution-history attribution supplies observed timing and rejection/cancellation facts; it does not infer why a market moved or what an unfilled trade would have earned.
