# Funded pause and resume acceptance

Verified 2026-09-05 Pacific. This verifies software lifecycle behavior using an isolated synthetic account and an explicitly stubbed eligible-evidence assessment. It is not a genuine eligible promotion or provider-backed paper smoke. Production fixture gates remain unchanged and reject fixtures.

## Automated restart path

`tests/research/test_release_lifecycle.py` joins the previously separate funding, partial-fill, restart, pause, approval and return-accounting cases:

1. Activate a synthetic $10,000 envelope and approve an exact 30-share buy at $100.
2. Claim one durable attempt, let the fake broker accept and fill 10 shares, then lose all local acknowledgement.
3. Recreate the application on the same database and pause while cancellation acknowledgement is unavailable. The position and allocation remain intact.
4. Recreate the application again. Submission of the original ticket performs lookup/reconciliation, preserving exactly one economic order.
5. Observe cancellation of the unfilled balance. Reject resume using an old review; prepare and approve a current review through the real API.
6. Verify the same committed terms, ten attributed shares, one allocation flow, $10,000 reconciled deployment equity and zero flow-adjusted return. Repeating the resume approval conflicts.

Focused result: **1 passed**, `/tmp/trademaster-release-lifecycle-tests.log`. Synthetic protocol-shaped account labels and the eligibility stub exist solely in this test. The broker fixture survives application recreation to model a separate remote broker; this does not claim an actual broker process was contacted.

## Browser path

The production browser used `/tmp/trademaster-funded-release/deployment.db`, with one partially filled synthetic entry and ten attributed shares. Through visible Quant controls, the operator paused, observed “partially filled then canceled,” prepared a current review showing $10,000 retained equity/$9,000 attributed cash, and explicitly approved resume. The deployment returned to paper-active with the same allocation. A second pause and browser reload showed “Committed allocation retained” in Brief. No JavaScript exceptions were observed.

`/tmp/trademaster-funded-release/current-review.png` shows the exact resume action and the visible SYNTHETIC eligibility-stub disclosure. Its “broker paper” protocol fields are fabricated in this isolated harness to exercise positive controls; they are not evidence of provider acceptance. The initial order/target was prepared by a test helper, so this browser check does not assert strategy evaluation or initial-order creation. Those flows have separate acceptance records.

Remote requests were disabled. No credentials, real account or money were used. The browser and owned API/web servers were stopped after verification. Provider-backed execution remains conditional on genuine eligible evidence, configured paper credentials and the existing per-order human approval.
