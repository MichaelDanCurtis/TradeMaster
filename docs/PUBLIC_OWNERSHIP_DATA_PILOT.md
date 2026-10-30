# Free historical institutional-ownership data pilot

September 8, 2026. This is a source audit for the cash-redeployment research
branch, not an investment result. New data subscription spend: **$0**.

The SEC publishes free bulk Form 13F archives, including historical submissions
and amendments. The 2019 Q2 archive was downloaded and parsed locally:

| Measurement | Observed |
|---|---:|
| Compressed archive | 54,098,902 bytes |
| Submissions | 7,144 |
| Raw position rows | 2,301,992 |
| Position rows without a matching submission accession | 0 |
| Managers with one original March 31 report and no same-period amendment in this archive | 4,882 |
| Rows in that original, unamended subset | 1,860,772 |
| Managers in that subset reporting Red Hat common shares | 655 |

The Red Hat subset is an ownership-plumbing example related to a known cash
acquisition, not a selected profitable event. Its 1,010 raw position rows are
not 1,010 independent managers. Shared discretion and duplicate rows need economic
reconciliation before calculating aggregate exposure.

Three managers were selected deterministically by a hash of their CIKs. Their
original public XML information tables contained 1,341, 7 and 601 positions.
All **1,949 positions** matched the bulk data on issuer/class labels, CUSIP,
reported value, share count, share/principal type, option type and investment
discretion after matching whitespace normalization. The initial strict comparison
found 50 label-format differences; both strict results and the subsequent
whitespace review are preserved. No numeric fields or identifiers were changed.
The original submission headers identify 13F-HR reports for March 31, 2019.
This is a spot check, not certification of all 2.3 million rows.

For these 2019 filings, reported `VALUE` is in **thousands of dollars**, while
`SSHPRNAMT` is a separate share or principal amount. The SEC changed the value
reporting unit starting January 3, 2023. Do not mix those units when joining
periods. [SEC archive](https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets),
[data dictionary](https://www.sec.gov/files/form_13f_readme.pdf).

The raw archive, source documentation, source receipts and audit are stored at
`.research-artifacts/public-13f-bulk-pilot-2026-09-08/`. The `original-crosscheck/`
subdirectory preserves the three original-filing comparisons and the subsequent
label-format review.

## What this enables next

Prepare a dated manager–security ownership graph from reports publicly filed
before each event. Reconcile amendments and shared discretion, qualify the cash
recipient/security/event terms, and map candidate destinations to historical
tradable securities. Compare any implied flow measure against market/industry
momentum and shuffled-ownership controls before considering return claims.

Public filings describe lagged reported positions. They do not establish that
those positions survived until merger completion, that money was received at the
assumed time, or that a manager reinvested it proportionally. Manager-level reports
also do not reproduce a proprietary fund-by-fund holdings dataset. The SEC's
current bulk archives include reprocessed data and do not replace original-source
checks. One filing quarter does not provide complete amendment or confidential
holdings history.

Reproduction scripts:

- `scripts/research/audit_public_13f_bulk.py`
- `scripts/research/crosscheck_public_13f.py`
- `scripts/research/review_public_13f_whitespace.py`

These steps are read-only public data operations with write-once local artifacts.
They do not submit orders or use a paid data provider.

## Follow-on result

The separately frozen [cash-flow pilot](CASH_FLOW_PILOT.md) has now completed on
Red Hat, Tiffany and Varian. Its 20% event sleeve did not improve on SPY or
matched/shuffled controls. That result does not alter this original source audit;
the follow-on preserves its own protocol, data-quality revision and outcomes.
