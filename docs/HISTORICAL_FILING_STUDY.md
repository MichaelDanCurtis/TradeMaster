# Historical filing-stability test using existing access

The F1-SP500-EW-v1 historical test completed its terminal-wealth replay. It did
not beat SPY in this interval. No data subscription was purchased.

| Cost per traded side | Filing stability CAGR | SPY CAGR | Difference |
|---|---:|---:|---:|
| 11 bps | 21.38% | 22.86% | -1.48 percentage points |
| 22 bps | 20.85% | 22.75% | -1.90 percentage points |

At 11 bps, $100,000 became approximately $160,010 in the strategy and $164,770
in SPY. The strategy held 159–165 stocks per quarter. This is an exploratory
whole-account comparison; attribution to the filing signal is still unproven.
The same-eligible-stock control needs additional corporate-action repairs, and
the full-universe control retains identity conflicts.

[Detailed result and limitations](../.research-artifacts/filing-sp500-ew-alexion-repair-2026-09-08-r4/report.md).

![Observed historical wealth](../.research-artifacts/filing-sp500-ew-alexion-repair-2026-09-08-r4/comparison.png)

The experiment covers April 1, 2019–September 3, 2021, with ten quarterly decisions.
The dated S&P membership reconstruction has 560 distinct securities across those
dates. A pinned public historical issuer archive supplies candidate identifiers
for all 560, representing 543 distinct issuers. Thirteen stock/date entries
conflict between the public histories; they are excluded from filing eligibility
and prevent an unqualified full-membership control. Numeric identity coverage is
not complete historical security-lineage qualification.

The expanded metadata pass completed 543 issuer histories and identified 5,479
candidate filing pairs requiring 7,542 distinct original documents. Capture and
normalization completed: 5,274 pairs passed structural qualification, while 205
did not. Verification hashed 14,845 raw sources and independently checked set
arithmetic, availability and ranking. This uses the same document parser; it is
not an independent semantic audit.

The first capture attempt exposed a legacy HTML comment parsing error. A tested
identity-view adapter fixes it while preserving the original narrative and all
investment rules. The new run records this engineering repair before any return
results; the earlier attempted run is retained.

Frozen original capture and initial replay root:
`.research-artifacts/filing-sp500-ew-2026-09-07-r2/`

The completed pipeline captured originals, normalized text and froze selections
without prices before valuing portfolios with the merger-entitlement engine.
It compares the highest-stability third with the same filing-eligible stocks,
the full historical membership where accountably observable, and SPY buy-and-hold.
Cost assumptions are 11 and 22 basis points per side. Missing held prices prevent
an unqualified full-period result; stocks are not removed based on their outcomes.

The initial selected-portfolio replay stopped at Alexion's acquisition. A separate
valuation-only amendment added the actual $60 cash plus 2.1243 AZN ADS entitlement,
using captured positive-volume successor prices and measured adjustment factors.
The original selections, input prices for other names, events and SPY replay are
unchanged. The amendment is stored in
`.research-artifacts/filing-sp500-ew-alexion-repair-2026-09-08-r4/`.

Biogen's November 6, 2020 trading halt remains a missing daily mark. Terminal
wealth completes, but daily volatility, Sharpe and beta are not qualified.
Observed drawdown was 36.28% versus SPY's 32.05%; missing marks can understate
maximum drawdown. Merger settlement and fractional entitlements are modeled
approximately, not reproduced from broker receipts.

The amendment passed separate transaction-cost arithmetic replays and an audit
of unchanged inputs, unaffected prices, benchmark equality and delivered cash/shares.
The relevant filing and accounting suite passed 42 tests. Do not promote this
variant or tune it against the observed outcome. The remaining matched-control
work can establish attribution, but it cannot change this frozen portfolio's
observed failure to meet the SPY objective.

The interval is shorter than three years and has already been examined in other
research. It cannot establish the rolling 36-month objective. Community
issuer mapping, historical membership, source coverage and economic-entitlement
accounting remain explicit limitations, even if a return curve completes.

A current SEC ticker lookup found 69 possible additions but included reused symbols.
Those current matches were not used. Instead, the dated archive identifies former
issuers such as Anadarko, SunTrust, Red Hat and Celgene. The pinned source, code,
license and candidate audit are recorded in
`.research-artifacts/filing-free-identity-audit-2026-09-07/history-source/`.
The mapping adapter checks date ranges and conflicting CIKs before use. The
archive can incorporate later corrections and approximate dates, which remain
explicit limitations. [Archive and documented caveats](https://github.com/lawcal/sp500-components-history).

The inherited-map attempt was stopped before return scoring. Its sources were
reused without changing text scores, weights, entry delays or cost assumptions.
The expanded run records the source repair and archives the frozen code. Capture
uses four workers and a global spacing of 0.2 seconds between requests (at most
five requests per second).

Reproduction:

```sh
PYTHONPATH=. .venv/bin/python scripts/research/historical_filing_study.py freeze --root NEW_ROOT --identities .research-artifacts/filing-free-identity-audit-2026-09-07/history-source/qualified-candidates.json
PYTHONPATH=. .venv/bin/python scripts/research/historical_filing_study.py metadata --root NEW_ROOT
PYTHONPATH=. .venv/bin/python scripts/research/historical_filing_study.py plans --root NEW_ROOT
PYTHONPATH=. .venv/bin/python scripts/research/historical_filing_study.py capture --root NEW_ROOT
PYTHONPATH=. .venv/bin/python scripts/research/historical_filing_study.py normalize --root NEW_ROOT
PYTHONPATH=. .venv/bin/python scripts/research/historical_filing_study.py targets --root NEW_ROOT
PYTHONPATH=. .venv-prediction-lab/bin/python scripts/research/historical_filing_study.py score --root NEW_ROOT
PYTHONPATH=. .venv-prediction-lab/bin/python scripts/research/report_historical_filing_study.py --root NEW_ROOT
```

Capture and metadata resume from hashed source receipts. Signal, target and result
artifacts are write-once. The numeric environment now includes the same lxml,
BeautifulSoup and httpx versions used by the application environment.
