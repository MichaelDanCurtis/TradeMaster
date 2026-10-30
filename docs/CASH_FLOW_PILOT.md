# Institutional cash-flow pilot

September 8, 2026. The first three-event historical test completed. The frozen
proportional-cash rule did not improve on SPY, the matched control, or typical
shuffled cash allocations. New data subscription spend: **$0**.

| Whole-account portfolio | CAGR at 11 bps/side | CAGR at 22 bps/side |
|---|---:|---:|
| SPY | 22.41% | 22.26% |
| Cash-flow overlay | 21.94% | 21.67% |
| Momentum overlay | 21.99% | 21.73% |
| Sector/liquidity/momentum-matched overlay | 22.32% | 22.05% |

The interval was July 10, 2019–April 30, 2021. Portfolios held a 20% stock sleeve
for ten sessions after the Red Hat, Tiffany and Varian cash-merger completions,
with 80% SPY during those windows and 100% SPY otherwise. Annualized results
therefore describe a mostly-SPY account. At both cost assumptions, 79 of 100
size-grouped cash shuffles performed at least as well as the actual linkage.

This is a three-event feasibility result, not independent-event significance or
proof against every institutional cash-flow mechanism. It is not a deployment
candidate, and the rule will not be tuned against these outcomes.

Seven SEC archives and dated pre-event raw prices were captured and hashed.
Independent arithmetic, timing and ranking checks passed before scoring; six
focused graph tests passed. The primary portfolio ledgers agreed with a separate
transaction-cost solver. All 104 variants completed at both cost levels, with
no missing daily marks in the primary portfolios.

A pre-outcome revision excludes issuer-name/CUSIP disagreements found in the raw
bulk data. Strict matching retained 217, 26 and 29 cash-holding managers for the
three events respectively. Unmatched holdings retain unallocated weight rather
than inflating demand for the securities that can be mapped. The initial version
and its targets remain preserved, without return scoring.

Lagged manager holdings do not establish fund-level reinvestment or actual
payment timing. The test uses public completion as its event trigger. Historical
issuer mapping remains a candidate name/CUSIP bridge, and coverage is limited.
Liquidity matching is not market-cap matching; stock-financed controls remain
outside this small pilot. No paper/live broker orders were submitted, and the
separate forward study and paper-account observation plans are unchanged.

[Full report and event-by-event results](../.research-artifacts/cash-flow-pilot-2026-09-08-r2/report.md).

![Cash-flow pilot comparison](../.research-artifacts/cash-flow-pilot-2026-09-08-r2/comparison.png)

Reproduction: `scripts/research/cash_flow_pilot.py` freezes, captures and builds
targets; `verify_cash_flow_targets.py` checks them; `score_cash_flow_pilot.py`
scores frozen portfolios; `report_cash_flow_pilot.py` produces the report. Stages
use write-once artifact roots and reject changed frozen dependencies.
