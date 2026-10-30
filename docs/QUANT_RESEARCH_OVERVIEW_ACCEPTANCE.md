# Research briefing and resources acceptance

Verified 2026-09-05 Pacific against the current checkout. This closes the Brief and Settings integrations in the design's existing-surface table. It does not establish investment evidence or provider readiness.

## Implemented behavior

`GET /api/research/overview` projects durable experiment states, evidence limitations, deployments awaiting review, latest enrolled-account reconciliation, and exact hypothesis-family trial/cost usage. Returned lists are bounded and include global totals. The read neither dispatches research nor contacts a data/model/broker provider. Runtime engine availability, recent worker heartbeat and configured model roles remain separate facts.

The dashboard and Settings receive only the new overview-read permission. They do not gain research editing or deployment authority. Brief opens Strategy Research, Quant and Performance directly. Settings shows worker/engine health, model pins, family costs and data capabilities. Provider configuration and declared import provenance are not labelled verified entitlements.

Initial and manual reads, periodic refresh and abort-on-unmount are implemented. A failed refresh preserves the last successful view with an explicit stale-data message. Empty accounts/experiments/budgets remain empty. Brief no longer displays the old hardcoded “Markets live” badge with absent quotes.

## Verification

- Backend overview, room-policy and research API checks: **18 passed**, `/tmp/trademaster-overview-tests-final.log`. Includes exact Decimal budget aggregation across all trials and unknown designer charges, bounded lists, fixture/negative evidence, funded pause projection, latest discrepancy replacing a previous reconciled receipt, and unchanged write permissions.
- Frontend suite: **160 passed**, `/tmp/trademaster-overview-webtests-final.log`.
- Production build: passed, `/tmp/trademaster-overview-build-final.log`, with four pre-existing warnings recorded in implementation status.
- Production browser at 1280px: empty and populated Brief/Settings, keyboard navigation to all three destinations, API-offline stale-data retention, browser reload/API restart, persisted 6/30 trials and $0.10 charges/$9.90 remaining, and a newly reconciled unexplained cash discrepancy. No horizontal document overflow or JavaScript exceptions observed.

Browser artifacts are in `/tmp/trademaster-overview-ui/`: `empty.png`, `settings-empty.png`, `brief-final.png`, `settings-populated.png`, and `discrepancy.png`. Earlier empty screenshots precede the quote-status and text-contrast refinements. The populated final Brief and discrepancy screenshots include those refinements. All screenshots were visually inspected. Test servers and browser were stopped after verification.

The isolated SQLite fixture contained one completed synthetic experiment, one queued experiment, an unfunded paused review and a synthetic account baseline. A later unexplained $100 cash difference generated a real negative reconciliation through the production accounting repository. Remote transports were blocked; no model, market-data provider or real paper account was contacted.
