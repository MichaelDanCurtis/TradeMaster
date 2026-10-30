# Research using public data and existing access

September 7, 2026. The user rejected new paid data subscriptions. Incremental
data-provider budget is **$0**. This decision supersedes the subscription
recommendation in the preserved first-pilot report. No subscription was purchased.

## What is already available

- The SEC pilot captured 200 original documents and produced 100 structurally
  validated year-over-year comparisons. These are engineering results, not returns.
- The existing historical event panel contains 745 symbol entries and dated
  community S&P membership reconstruction. It spans January 2016 to September
  2021; that is a date range, not a claim of complete prices for every security.
- Previous selected portfolios were reconciled over March 2019–September 2021.
  This does not establish that every possible filing-strategy holding is covered.
- Existing Alpaca access, captured corporate-action records and SEC facts can
  be reused. SEC submissions, original filings and XBRL APIs need no paid key.
  [SEC documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

## Next experiment: F1-SP500-EW

Prepare a separately registered, equal-weight historical S&P filing-stability
experiment. This changes both universe and weighting from F1's historical
top-1,000 capitalization-weighted specification; it must not be presented as
an exact replication. Keep F1's fixed text score, original-filing identity rules,
availability lag, freshness limit and quarterly rebalance.

Use dated membership to select securities, then the highest-stability third of
the filing-eligible set. Compare against an identically eligible equal-weight
universe, a full historical equal-weight universe where accountably observable,
and dividend-reinvested SPY. Report coverage, turnover, implementation costs,
concentration and drawdown alongside returns. Rank ties deterministically by
stable identity. Freeze the detailed protocol and data manifest before scoring.

Start by auditing the existing 2019–2021 reconciled interval because those
corporate-action repairs already exist, not because of new strategy returns.
This interval is shorter than 36 months, so it can give an initial mechanism
test but cannot establish the roadmap's rolling three-year objective. The
period has been examined in previous research and is not an untouched holdout.
Extend history based on source qualification, without choosing endpoints from
favorable returns.

Retain missing-price securities in the coverage ledger. Do not select the
universe by future price availability or silently remove bankrupt companies.
Resolve identities and terminal proceeds from original merger, bankruptcy and
issuer records where possible. Unresolved held positions require explicit
valuation gaps or defensible bounds; an incomplete curve is not a completed
SPY comparison. Paid data is not the default response to a gap.

## Other branches remain possible without subscriptions

Continue harvesting public merger-completion, ownership and tender filings.
Select events from contemporaneous filing indexes rather than today's surviving
issuers. Original documents supply event terms; quotes, realizable proceeds and
ownership timing still require separate verification. Use disclosed management
guidance as an expectations proxy, not as a claimed analyst-consensus history.

Historical capitalization can later be reconstructed from filing-specific share
counts and compatible prices where share classes and corporate actions qualify.
Public float is not total market capitalization. This reconstruction is optional
for the equal-weight experiment and does not block it.

The tradeoff is more collection and reconciliation work, with explicitly limited
coverage. A complete free commercial-feed equivalent has not been demonstrated.
No new return test has been run as part of this budget revision. Existing frozen
research artifacts and paper/forward trial contracts remain intact.
