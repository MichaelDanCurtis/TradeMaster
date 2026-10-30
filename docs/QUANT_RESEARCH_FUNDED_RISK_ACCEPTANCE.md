# Funded quantity risk acceptance

Verified 2026-09-05 using synthetic observations only. This completes the descriptive deployment quantity-risk comparison, not funded performance accounting or the complete implementation plan.

## Behavior and interpretation

New deployment evaluations preserve separate reports for proposed whole-share quantities and reconciled attributed holdings. Both use available raw prices from the pinned decision session, so differences reflect quantity changes rather than mixed price timestamps. These observed holdings can have been reconciled after the information cutoff; the report explicitly describes their revaluation at decision prices. It is not a current broker-mark portfolio or a realized performance series.

Each report retains dollar exposure, position/group fractions of the committed nominal funding envelope, the reviewed concentration limits and breaches, unused nominal envelope, and headroom after required cash reserve before fees. Neither unused envelope nor reserve headroom is represented as settled cash or buying power. Existing exact-order account/funding checks remain authoritative, including pending orders, fees, current marks, approvals and serial sell-before-buy execution.

Covariance is calculated at the quantity-derived weights using aligned available total returns and explicit available splits/dividends. Trend uses its frozen volatility window; guidance uses a fixed 63-session descriptive window that does not change event admission or sizing. A missing historical observation gives exposure-only status; a missing decision price prevents valuation. There is no substitution, shortened window or invented estimate.

Dollar volatility is retained alongside the computation denominator and envelope-relative volatility. If appreciated holdings exceed their original nominal envelope, the calculation uses gross holdings value as its covariance denominator and converts back to full dollar risk. It does not scale away the overrun or infer account leverage from a nominal funding overrun. Zero observed variance leaves normalized contributions undefined. Short samples, constant-value cash assumptions, omitted pending orders/costs/liquidity, and uncertainty outside the sample remain explicit.

Quant provides a comparison table plus per-symbol/group concentration and covariance details. Existing ideal-weight trend risk stays separate. Older evaluations retain an explicit absence message rather than being silently backfilled. The new module participates in the evaluation build fingerprint, and immutable evaluation records preserve the exact source, terms and reconciliation references.

## Verification

Broad backend command:

```sh
.venv/bin/python -m pytest tests/research tests/ui/test_api.py tests/ui/test_broker_service.py tests/ui/test_alpaca_broker.py tests/ui/test_repository.py tests/ui/test_room_policy.py tests/test_role_models.py -q
```

**356 passed, 12 explicit native integration skips**, 81.27 seconds, `/tmp/trademaster-funded-risk-regression.log`. The earlier focused risk/evaluator/guidance/jobs/covariance run passed 36 checks before the final corporate-action test; the broad run includes that test. No LEAN strategy/replay kernel was changed, and the native suite was not rerun here.

Independent cases verify:

- Three daily observations with opposite 1% moves, 2 versus 1 shares at $99.99: $299.97 gross exposure and annualized dollar volatility `0.9999 × sqrt(252)`. Contributions are 200% and −100%, preserving sample hedging.
- Ten times those holdings preserve ten times dollar risk, the $2,999.70 gross computation basis, negative nominal headroom, and position/group breaches.
- Missing/late history versus missing current decision prices, all-cash quantities, and later observations not affecting an earlier cutoff.
- A two-for-one split followed by a $1 per-post-split-share dividend removes mechanical price changes only when those actions were available; raw valuation remains unchanged.
- Persisted proposal risk uses exact rounded shares, differs from ideal weights, and remains separate from observed holdings and repeated evaluation requests.

Full frontend **160 passed**, `/tmp/trademaster-funded-risk-webtests.log`. Production build passed, `/tmp/trademaster-funded-risk-build.log`, with the four existing unrelated warnings. React review checked typed fields, native keyboard-operable disclosure controls, table captions/row headers, explicit unavailable values and bounded table overflow. Python compilation and whitespace checks passed.

## Browser evidence

The credential-free fixture harness in `/tmp/trademaster-funded-risk-ui` created one synthetic three-share fill, reconciled it and evaluated a 48-share proposal. The browser displayed $308.04 of held exposure versus $4,928.59 of proposed exposure at the same decision price, with separate dollar risk, reserve headroom, ideal weights and contribution details. Reload/reselection preserved the comparison. The app produced no JavaScript exception, error overlay, deployment alert or horizontal page overflow. Navigation/disclosures were verified with keyboard focus and Enter.

Deployment: `dep_d582e9817d484d5dbeb72d6de259435b`. Screenshots: `initial.png`, `comparison.png`, `contributions.png`; exact numeric references are in `references.json` in that directory. Positive activation was stubbed inside the isolated fixture, and broker-paper/prospective metadata was fabricated for protocol checks. These values are not investment evidence or real broker validation.

The browser and both acceptance servers were stopped after verification. No remote provider/model call, real order, purchase or commit was made.

## Still required

The complete release needs deployment capital/equity and flow-adjusted return attribution, theoretical/approved/filled delay and rejection attribution, strategy-design assistance, genuine-data/provider verification and the remaining labelled/paired-event checks. Descriptive risk does not supply those results. Provider-backed smoke remains separate and conditional on configuration and human order approval.
