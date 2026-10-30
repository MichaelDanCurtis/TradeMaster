# Portfolio stress testing

Open **Research → Portfolio stress**. Capture the current Alpaca paper account, then
save several scenarios against that exact observation. Presets include unchanged
prices, all holdings down 20%, and the largest direct holding down 25%. Edit the
common change and per-holding overrides to construct simultaneous custom shocks.
An override replaces the common shock. Cash and quantities remain fixed.

Results show the portfolio dollar and percentage change, stressed equity, holding
values and before/after concentrations. Comparisons include only scenarios using
the same snapshot. Broker open orders and deduplicated local/scheduled commitments
are shown separately, without assuming fills. Positive and negative shocks are
allowed within explicit bounds; nonfinite and below-total-loss inputs are rejected.

The calculation requires a complete, positive-equity paper snapshot with long
holdings and cash plus positions reconciling to equity within five cents. A residual
within that tolerance stays unchanged. Stressed equity at or below zero produces
undefined concentration percentages rather than division by zero. No probability,
VaR, observed drawdown, ETF look-through, margin liquidation, trading costs, taxes,
dividends or automatic rebalancing is inferred. No orders are created.

Source snapshots and calculation receipts are stored by SHA-256 under
`.research-artifacts/stress/objects`. Saved desk records retain assumptions, code
fingerprint and result. Export verifies both the receipt and account evidence.
The normal single local API process is supported; scenario POSTs retain request
keys to recover uncertain responses without saving duplicate scenarios.

## Native verification — September 6, 2026 Pacific

Browser-captured source `desk_93d7bfb6bb654586bd62b8a4ab2a9775` contains five direct
holdings and a private paper account. Three browser-created scenarios were checked
by independent decimal calculations and exported receipt/source hashes:

- Unchanged prices: zero dollar change.
- Largest holding (MSFT) down 25%: approximately -$882.44 / -0.87525% account equity.
- All holdings down 20%: approximately -$1,987.48 / -1.97128% account equity.

These are hypothetical changes to the captured account, not trading losses or
forecasts. The account's cash explains why its overall percentage change is smaller
than the holding-price shock. Evidence is in `.research-artifacts/stress-verification/`.
Tests cover arithmetic, cash preservation, override semantics, total loss, undefined
weights, invalid/unknown inputs, unreconciled account rejection, request replay,
export corruption and provider-error redaction.
