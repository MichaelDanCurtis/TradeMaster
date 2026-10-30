# Research roadmap: new ways to challenge SPY

Prepared September 7, 2026 (America/Los_Angeles). Status: **research program; the F1 equal-weight and three-event O1 proxy variants have run; wider experiments remain pending**. Research priorities reflect the user's request for less obvious approaches and an investment horizon under five years. They do not authorize purchases, new broker activity, or changes to existing frozen trials.

Implementation update: the [first source and filing-stability pilot](EVENT_RESEARCH_PILOT.md) has run on 100 original filing pairs. That first pilot supplied engineering evidence; the separate F1 equal-weight follow-on now has the result below.

Budget revision: **no new paid data subscriptions**. The [public-data execution plan](RESEARCH_WITHOUT_NEW_DATA_SPEND.md) supersedes earlier provider-purchase recommendations and defines a separate historical S&P equal-weight filing experiment now tested as described below. It does not change the original cap-weighted F1 specification.

Execution update: the [historical S&P filing study](HISTORICAL_FILING_STUDY.md) is
complete for terminal wealth: 21.38% CAGR versus SPY's 22.86% at 11 bps per
traded side, April 2019–September 2021. At 22 bps the comparison is 20.85% versus
22.75%. This separately frozen equal-weight variant did not meet the SPY objective.
It used 5,274 structurally qualified pairs from 7,542 documents. One halt day limits
daily risk qualification; the matched eligible control and full-membership control
remain incomplete. No claim of signal alpha, untouched validation or a three-year
result follows.

A [free institutional-ownership archive pilot](PUBLIC_OWNERSHIP_DATA_PILOT.md) also parsed 2.3 million historical position rows and cross-checked 1,949 sampled positions against original filings. The follow-on [three-event cash-flow test](CASH_FLOW_PILOT.md) completed:
21.94% annualized for a 20% event sleeve over SPY versus 22.41% for SPY alone at
11 bps per side; 79 of 100 cash shuffles did at least as well. This exact proxy
failed its first controls and is not a deployment candidate. Sparse identity and
ownership coverage limits inference about the broader mechanism.

**Recommendation.** Pursue three initial projects: changes in company filings, cash redeployment through institutional ownership, and corporate actions with advantageous terms for small holders. Use the first to obtain a relatively inexpensive historical verdict, the second as the most distinctive model opportunity, and the third to investigate a concrete advantage of having less capital. Expand into customer–supplier information and an integrated expectations model only after their required data and simpler controls qualify.

The shared research question is: **What changed, who is affected, what transactions might follow, and how much of that has already reached the price?** Each component must explain an economic mechanism, survive executable entry prices, and contribute enough dollars to improve the whole account.

**What beating SPY means here**

The primary objective is greater terminal wealth than dividend-reinvested SPY over rolling **36-month** investment periods, after implementation costs. Also report 12-, 24-, and 48-month outcomes; 60 months is boundary context. Individual trades can last days or months. Longer historical records help test this short investment horizon across different environments; we do not need to wait three years to run the historical experiments.

Proposed economic hurdle for the eventual combined research portfolio: a **median difference of at least 2 percentage points between strategy CAGR and SPY CAGR across rolling 36-month windows**, with no account borrowing and without materially worse crash losses. This is a design target, not an expected return or a promise. Report the worst windows and full-history CAGR as well; the median does not imply winning every three-year period. Before results are inspected, freeze window start dates and risk limits; suggested initial limits are equity beta no greater than 1.1 and full-evaluation-period maximum drawdown no more than 5 percentage points worse than SPY over identical dates. Report embedded fund leverage, duration, concentration and downside exposure separately: those two limits alone cannot establish equal risk.

Keep two scorecards. One measures actual whole-account performance against SPY. The other compares a strategy with an appropriate universe, sector, factor or asset-class control. A superior Sharpe ratio, a successful bond trade, or a long–short research spread does not by itself meet the SPY objective. A useful small-capacity opportunity can remain a supplementary feature even if it cannot meet the whole-account hurdle.

**What our previous work already established**

The current project evidence does not establish a robust SPY-beating strategy. Generic price forecasts, headline polarity and simple five-day reversal have already received unfavorable tests. Apparent stock-selection gains were sensitive to historical membership and coverage. The fixed insider-purchase plus financial-quality strategy is [retired](research-decisions/insider-quality-final-retirement.json); adding these ideas to that retired strategy is outside this program.

Reuse the [forecast comparisons](FORECAST_CHALLENGER_BENCHMARK.md), [historical membership findings](PREDICTION_HISTORICAL_VALIDATION.md), [news research](NEWS_SIGNAL_RESEARCH.md), and [final insider-quality test](INSIDER_QUALITY_FINAL_TEST.md) as controls and lessons. Preserve the separate [forward study](PREDICTION_FORWARD_STUDY.md). This document defines new hypotheses, not a favorable reinterpretation of old results.

**Prioritized experiments**

| ID | Hypothesis | Initial position horizon | Reason to investigate | Principal weakness |
|---|---|---|---|---|
| F1 | Filing stability predicts relative returns beyond ordinary exposures | Quarterly portfolio; 60-session diagnostic | Public original documents, cheap baseline, recent independent study | Could be a stability/size exposure; costs and executable timing may erase benefit |
| O1 | Cash distributions induce purchases of other institutional holdings | 10 sessions | Predict a flow of money with an identifiable origin | Public holdings are stale; reinvestment is discretionary |
| T1 | Eligible odd-lot priority improves attainable tender proceeds | Offer-specific, days to weeks | Some terms explicitly favor a small beneficial owner | Very limited capacity, eligibility and delivery risk |
| T2 | A CEF tender or liquidation creates a realizable discount opportunity | Offer-specific, weeks to months | An explicit exit mechanism can be modeled | Proration, NAV movement, costs; published contrary evidence |
| G1 | Customer operating events propagate to exposed suppliers | 20 sessions | A dated relationship can identify affected firms | Relationship history and ordinary momentum can explain the apparent signal |
| E1 | Guidance, cash conversion and price reaction jointly reveal mispricing | 60 sessions | A route toward a more capable integrated model | Weakest direct evidence for this combined architecture |

These are priorities for testing, not rankings of expected investment returns. F1, O1 and a shared T1/T2 data pilot form the first batch. G1 and E1 are conditional follow-ons.

**F1 — Read what changed between filings**

Compare a company's original 10-K or 10-Q with the corresponding fiscal period a year earlier. Later, identify specific changes: customer concentration, revenue recognition, debt terms, segment reporting or operating risks. A hypothetical business reporting healthy sales while adding a previously absent customer-loss disclosure deserves a different analysis from a business merely updating standard legal language.

The original *Lazy Prices* paper motivates this line. A June 2026 Research Affiliates study reports persistence through September 2025 in the largest 1,000 U.S. stocks. Its quarterly long-only buckets use that universe as the benchmark, exclude trading costs and management fees, and are not a demonstrated SPY replacement. Its separate event-window analysis is overlapping. That is encouraging replication evidence with implementation work still to do. [Original research](https://www.nber.org/papers/w25084), [2026 practitioner study](https://media.researchaffiliates.com/1117_nlp_for_long_horizon_factor_investing_d39e26f476.pdf).

The first specification is deliberately fixed: original filings only, table/stop-word removal, whole-document Jaccard similarity, same-quarter year-over-year comparisons. Use the latest comparable original filing, no older than 180 calendar days, publicly available at least two trading sessions before quarterly rebalance. This freshness limit is our proposed pilot assumption; it applies to the newer document, not the year-earlier comparison. Mark missing or stale pairs explicitly and report excluded capitalization and reasons. Buy the highest-similarity third of a historically identified top-1,000 common-stock universe, capitalization weighted and fully invested. Compare with both SPY and the identically data-eligible capitalization-weighted universe; report the full-universe control separately to expose coverage selection. No insider, profitability, valuation or volatility-selection overlay enters F1. Similarity measures stability; it cannot identify whether an individual change is beneficial or adverse.

Score a 60-session residual-return diagnostic as a mechanism check, but do not choose the best of several holding periods. Archive amendments separately; this first specification does not substitute them for originals. Later semantic changes form one separately registered challenger with exact before/after evidence and numerical calculations performed in code.

Controls: ordinary factors, sector-wide legal changes, whole-document versus section similarity, no-LLM features, masked company names, and removal of the best contributors. Stop the investment branch if executable net results are explained by those controls. Stop the semantic branch if it cannot improve the simple baseline. If the effect is mainly avoiding losers, explicitly test a fully invested substitution portfolio; short-side research evidence does not establish a useful long-only allocation.

**O1 — Follow cash into other holdings**

An all-cash acquisition pays the target's owners. Some institutional owners may redeploy that money into securities they already own. Our hypothesis is that the recipient holdings, especially where estimated demand is large relative to ordinary trading volume, can be identified before the entire adjustment occurs.

Chen's *Cash Induced Demand*, published in JFQA in 2024, documents related institutional reinvestment and price effects. Its transaction/holdings evidence uses institutional datasets, including proprietary transactions; it does not establish that a public-filing implementation works. [Primary research](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/cash-induced-demand/6911008EC35F4B1D1D99BCB1427F9C61).

The first experiment uses publicly confirmed all-cash merger completions and known shareholder-payment schedules. Estimate cash recipients using holdings already publicly available, distribute a hypothetical reinvestment amount proportionately over their other disclosed holdings, and scale estimated demand by trailing dollar volume. Enter no earlier than the next session after a usable public confirmation; use a fixed ten-session exit. Preserve the event's announcement, completion, payment, disclosure and entry dates separately. A future payment schedule is a forecast input, not evidence that cash has arrived. Announced buyback authorizations are not cash payments and are excluded from this first experiment.

The ownership graph must distinguish a **fund** from a **manager**. A manager's 13F can aggregate many accounts; it is only a coholding proxy, not proof that the same fund receives and reinvests cash. Run a fund-level version only where the records actually identify the fund. Duplicate ownership observations must not double-count cash.

Form 13F generally has a 45-day quarter-end reporting deadline. Public N-PORT holdings are delayed snapshots; the 2024 monthly-publication changes were delayed, and a February 2026 proposal would retain quarterly publication. Use actual public availability, not presumed contemporaneous holdings. [SEC 13F guidance](https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f), [2026 N-PORT proposal](https://www.sec.gov/rules-regulations/2026/02/s7-2026-05).

Controls: sector/size/momentum-matched securities, stock-financed merger events, ownership links shuffled within comparable groups, and a price/volume-only model. Assess stale ownership and target shares acquired by merger arbitrageurs before completion. Abandon the public-data version if it requires unavailable holdings, preconfirmation fills or returns explained by ordinary factors. Reinvestment is a behavioral hypothesis; no manager is assumed obligated to follow our proportional rule.

If this survives, the ambitious model estimates distributions of cash receipt, reinvestment timing and destination. Start with transparent graph arithmetic; advance to a small temporal graph learner only if it improves held-out net returns and calibration.

**T1/T2 — Calculate what an offer actually pays**

Some tender offers give qualifying holders of fewer than 100 aggregate shares priority over prorated larger holders. Lennar's November 26, 2025 final exchange results accepted valid qualifying odd lots in full while reporting approximately 8.604% proration for other shares. Consideration was Millrose stock, so full acceptance did not remove price or delivery risk. [Issuer final results](https://investors.lennar.com/press-releases/2025/11-26-2025-130116812).

This is an identifiable small-investor advantage. Build an offer parser covering eligibility, beneficial ownership, consideration, exchange-ratio caps, amendments, broker deadlines, withdrawal rights and delivery dates. Terms may aggregate holdings across accounts; the system must not manufacture eligibility by splitting accounts. [Example SEC offer terms](https://www.sec.gov/Archives/edgar/data/1830081/000121390025000757/sctoi_ex99a1arumble.htm).

For closed-end funds, require a published tender, approved liquidation or similarly explicit realization mechanism. A persistent discount alone is insufficient. BlackRock's 2026 conditional programs illustrate both opportunity and limits: intended tenders at 98% of NAV for at least 5% of shares after the stated discount trigger; holders may not have all tendered shares accepted. These are conditional terms, not guaranteed transactions. [Issuer program](https://www.blackrock.com/us/individual/literature/press-release/11-14-2025-pr-2026-discount-management-program.pdf).

There is serious contrary evidence: a 2021 reexamination finds ordinary tender profits disappeared in its newer sample and CEF tender profits were not significant after transaction costs. The new test must isolate current, actually executable terms and small-holder eligibility; it cannot assume every tender is attractive. [Published reexamination](https://link.springer.com/article/10.1007/s11156-020-00935-4).

Construct complete chronological cohorts within fixed dates, including withdrawn, extended, amended and unattractive offers. T1 and T2 remain separate experiments despite sharing a parser. Buy only after public terms; use the broker's earlier cutoff where known. Model final acceptance for outcomes, but never use realized proration or cancellation to select the original trade. Selection uses only conservative assumptions available then. On cancellation, use a predetermined next-executable-session exit; on completion, value proceeds and residual shares at actual availability. Unresolved delivery is unresolved capital, not an immediate exit.

The accounting is: accepted shares times actual proceeds, plus realizable residual holdings, plus distributions, minus purchase outlay and all costs. Never apply the tender price to the entire position unless all shares qualify and are actually accepted. Never count distributions twice through both adjusted prices and cash.

Report annual dollars and total-account contribution at illustrative account sizes of $100,000, $250,000 and $1 million. A hypothetical $2 spread on 99 shares is only $198 before costs. Ten such successful opportunities would contribute about 0.79% of a $250,000 account before costs and losses; this arithmetic is not a frequency or profitability forecast.

Stop where broker support, historical NAVs, quotes, failed-offer coverage or deliverable-security prices cannot be established. A successful tender sleeve may be valuable yet too small to be our primary return engine.

**G1 and E1 — The path toward a more capable model**

G1 builds a historically dated customer–supplier graph. For example, a customer cutting production could affect a supplier with disclosed exposure. Distinguish operating transmission from stocks simply moving together. Economic-link research supports testing this, while a later JFQA study attributes substantial linked-return predictability to shared momentum. [Original research](https://pages.stern.nyu.edu/~afrazzin/pdf/Economic%20Links%20and%20Predictable%20Returns%20-%20Cohen%20and%20Frazzini.pdf), [counterevidence](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/where-does-the-predictability-from-sorting-on-returns-of-economically-linked-firms-come-from/6B9F2560E0A27615572309C6F295AFBF).

First use exposure-weighted customer operating changes and returns to predict supplier 20-session residual returns. Freeze relationship direction, first-known timestamp and expiration policy. Compare with own/customer/industry momentum, reversed and shuffled links, and same-sector unrelated firms. Stop if links add nothing, are unknowable historically, or the return occurs before entry.

E1 combines prior guidance, new guidance, cash conversion, inventory/receivables, relationship events and the price move already observed. A business forecasting win is insufficient: the primary target is remaining 60-session residual return after realistic entry. Previously published management guidance and a rolling statistical forecast are expectation proxies; actual market consensus requires dated analyst estimates on comparable accounting definitions.

The first model is regularized regression or boosted trees. Its challenger adds evidence-linked textual changes and interactions. Ablate guidance, relationship information, text and observed price response separately. A 2026 working paper finds rapid earnings-related price adjustment and post-2016 strategy results consistent with efficiency, making post-jump entry essential. The integrated model is our proposed research architecture, not a literature-validated alpha engine. [Contrary earnings evidence](https://arxiv.org/abs/2601.08962).

**Architecture that these experiments could earn**

```mermaid
flowchart LR
    A[Original dated documents and market records] --> B[Verified changes and event terms]
    B --> C[Ownership and operating relationships known then]
    C --> D[Simple mechanism model]
    D --> E[Incremental return model after observed price reaction]
    E --> F[Costs, capacity and uncertainty]
    F --> G[Historical portfolio versus SPY and controls]
    G --> H[Qualified shadow research]
```

A minimal event record contains issuer/security identity, event type, prior state, new state, period affected, relationship, exact source span, source hash, publication time, observation time and extraction-completion time. Each relationship also needs validity dates and uncertainty. Offer outcomes and subsequent returns live in separate label records.

Historical replay eligibility uses verified public dissemination plus a processing delay frozen for that experiment. Today's retrieval and extraction timestamps document reconstruction provenance; they do not establish historical availability. Forward eligibility uses the latest of public release, actual receipt and extraction completion, followed by the permitted execution time. A document without a defensible historical availability time remains unqualified for historical trading claims.

Astra can extract difficult terms, compare passages, propose falsifiable mechanisms and challenge decisions. Numerical code calculates cash flows and returns. A trained model estimates the remaining opportunity and its uncertainty. Historical extraction using a current LLM is tagged retrospective: the model may know later outcomes even when its input is restricted. A 2026 accounting study shows anonymized numerical inputs can still produce look-ahead problems in commercial LLM forecasts. Require no-LLM baselines, name masking, economically invariant rescaling/perturbation checks and original-source evidence; these reduce diagnostic uncertainty without proving contamination absent. [Caution Ahead](https://doi.org/10.1111/1475-679x.70058).

The ambitious endpoint is a joint event-and-relationship model that learns which disclosures and cash movements transmit to which securities, on what delay, after how much price adjustment. It should also learn to abstain. Strong extraction, accurate business prediction and profitable portfolio decisions are three separately measured outcomes.

Start with sparse graphs, compact tabular models and cached document representations. Benchmark runtime and memory on the local Mac before selecting a larger model. Available memory is useful for larger batches and contexts; it does not supply independent historical events. No foundation-model training or new cloud spend is necessary to run the first baselines.

Reuse `tradingagents/research/evidence/` for bounded extraction and source validation, `tradingagents/research/evaluation/` for labels/comparisons, and the existing immutable artifact storage. Extend contracts only where event terms, graph dates or tender accounting require it. Research outputs remain separate from broker authority.

**Data work, ordered by the experiment it unlocks**

| Need | Initial source / alternative | Qualification required |
|---|---|---|
| Original filings and earnings exhibits | SEC archival documents and APIs | Accession identity, original versus amendment, public timestamp, comparable fiscal periods |
| Tradable historical universe and outcomes | Existing panels and Alpaca access; public membership and corporate-action records | Delisted securities, reused tickers, proceeds, membership dates, volume and tradeable prices |
| Dated fundamentals / capitalization | Original SEC facts and filing-specific share counts; equal-weight first experiment | Original versus revised values, filing-time availability, historical coverage and share changes |
| Institutional holdings | Actual public 13F and N-PORT filings | Manager/fund distinction, reporting lag, amendments, duplicate holdings, security identifiers |
| Tender economics | Schedule TO, issuer amendments and final results | Both failed and completed offers, bid/ask, NAV history, distributions, broker rules, delivery |
| Supplier relationships | Dated public disclosures | First-known relationship and exposure; discontinued links; no current graph projected backward |
| Analyst expectations | Public management-guidance proxy | Publication date, revision history and accounting comparability; not actual analyst consensus |

SEC APIs are useful public building blocks, but Company Facts coverage is not a complete segment/relationship dataset and current ticker mappings are not a historical security master. Preserve original filing-specific values. [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

Norgate advertises historical membership and extensive delisted coverage, with explicit exclusions including some rights, trusts and when-issued securities. Its historical index data does not supply announcement dates. Its local updater/Python workflow also requires Windows or a compatible VM. This earlier provider comparison is background only; the active plan uses public sources and existing access. [Coverage](https://norgatedata.com/data-content-tables.php), [data FAQ](https://norgatedata.com/data-package-faq.php), [system requirements](https://norgatedata.com/accessibility.php).

Earlier commercial-provider comparisons are background only. New subscriptions are out of scope. Reuse existing access and public records, disclose unresolved coverage, and narrow the claim or register an alternative experiment when a required field cannot be qualified.

A current web page bearing an old date is not automatically an original historical observation. Cache current sources for new forward evidence; qualify archived versions separately. Fix the particular historical data gaps needed by the first experiment before building a universal web crawler.

Include recurring data and inference expenses in account economics. Hypothetically, $5,000 a year of ongoing feeds consumes 2% of a $250,000 account before trading. Report research setup expenditure separately from recurring operating costs.

**Work sequence and deliverables**

| Stage | Work package | Concrete output | Decision |
|---|---|---|---|
| 0 | Freeze specifications and qualify small source samples | Experiment register; timestamp/identity audit; coverage and provider-gap report | Proceed where data supports the claim; label other branches blocked or descriptive |
| 1A | F1 cheap historical baseline | Paired originals, fixed Jaccard scores, continuous portfolios and coverage controls | Does filing stability add net value beyond the same eligible universe? |
| 1B | O1 cash/ownership feasibility in parallel | Dated event and holdings graph, fixed proportional-demand scores, placebos | Does any effect survive public disclosure lag and delayed entry? |
| 1C | Shared offer parser; separate T1 and T2 replays | All-offer register, acceptance/delivery ledger, annual dollar capacity | Is any spread attainable and large enough to matter? |
| 2 | Historical challenge of survivors | Chronological validation, cost/delay stress, concentration and risk attribution | Pass, fail, inconclusive, or useful only at limited capacity |
| 3 | One model challenger per surviving mechanism; then G1/E1 if justified | Frozen model, ablations, incremental net results and calibration | Does complexity earn its cost? |
| 4 | Combine surviving signals | Fixed combined portfolio versus SPY and matched controls | Does the complete account meet the return/risk hurdle? |
| 5 | Productize qualified research | Event evidence view, opportunity queue, experiment history, source freshness and outcome ledger | Can a user inspect evidence and act on a genuinely qualified result? |

Stage 0 starts with 100 paired filing records, 20 cash events and 20 offer records, selected by dates/identifiers without returns. These are engineering audit samples, not statistically sufficient investment tests. Enumerate the eligible population and every data rejection before accessing outcome labels. Audit critical prices, identities, terms and times with independent checks; any unresolved critical error blocks the affected record's use as qualified evidence.

Aim for the first cheap historical verdict in roughly one to two weeks of implementation, conditional on source access and clean histories. This is a planning estimate, not a scheduled job or a profitability deadline. Do not build all branches before testing F1. A completed data-feasibility failure is a useful stage result, not a reason to substitute clean survivors silently.

The full experiment protocol must freeze dates, universe rules, entry/exit, costs, portfolios, missing-data treatment, model variants and acceptance criteria before new outcome analysis. This document is a design draft, not that frozen protocol. First-batch common-stock eligibility should be based on historical identities, lagged size and predecision liquidity; final cutoffs belong in the stage-0 register. Different cohorts selected because their eventual prices are available cannot be passed off as the same universe.

Use the longest defensible history with meaningful modern coverage. Existing 2019–2025 project exposure means those years cannot be called untouched. Historical studies can reject weak ideas now; validation splits on previously examined dates must retain their exploratory label. Reserve a genuinely unexamined confirmation sample where one exists and begin a separate frozen observation stream for new outcomes after registration.

**Common testing and stopping contract**

- Train only on labels resolved before the decision. Fit preprocessing, factor exposures and model selection only on prior data. Purge overlapping outcome intervals across splits and group related issuer/deal events.
- Preserve failed firms, canceled offers and corporate-action outcomes. Never fabricate delisting proceeds or carry an untradeable final price indefinitely. If complete valuation is impossible, stop the portfolio claim and state the coverage limit.
- Use continuous capital-accounting portfolios, dividends, cash opportunity cost and actual capital lockup. Return statistics from overlapping event windows are diagnostics, not a funded portfolio.
- F1 begins with the existing 11/22-bps-per-side convention as transparent sensitivity cases. Execution qualification also requires spreads, participation and delay calibrated to the instruments; those fixed costs are not sufficient for every tender or small stock.
- Charge applicable commissions, spreads, slippage, tender fees and recurring data/inference expense. Use historically appropriate cash yield, with zero-cash-yield sensitivity. Embedded fund expenses are already reflected in returns/NAV; avoid double charging them.
- Report whole-account wealth, CAGR, drawdown, expected shortfall, beta, turnover, factor/sector exposure, capital utilization and contribution by issuer/event. Publish base and doubled implementation costs and one extra session of entry delay.
- Compare a fully active equity portfolio and one predeclared illustrative 80% SPY / 20% research allocation; unallocated research capital returns to SPY under the frozen rule. This is experimental sizing, not a recommendation for the user's money. Use actual blended returns, correlation and opportunity costs rather than adding standalone CAGRs.
- For intuition only, a 20% allocation earning 10 percentage points more than its replaced exposure contributes about 2 points before interactions and costs. This makes both signal strength and usable capacity explicit.
- Log every hypothesis, variant and abandoned run. Use calendar-block uncertainty with issuer/event clustering; adjust confirmatory comparisons for the tested family. Freeze the procedure and economically relevant effect size before labels. An interval including zero is inconclusive, not proof of success or proof of no effect.
- Historical rolling-window win frequency is descriptive; overlapping windows are not independent trials and their frequency is not a calibrated forecast probability.
- Finalize signal selection, combination weights and idle-capital rules before opening the combined portfolio's confirmation sample. A portfolio assembled from validation winners cannot be confirmed on those same outcomes. If no untouched sample remains, label the combined result exploratory even if all numerical hurdles pass.
- A preliminary survivor should beat the relevant control after costs and delay, with positive economic contribution across multiple eras. The combined portfolio must also clear the SPY hurdle. If performance relies on one deal, one sector, hidden leverage or a single selected era, retain it as exploratory.
- A model losing to its simple baseline is retired as a model even if the simple strategy survives. Record exactly what failed; do not automatically spend another round tuning it.

Alpaca paper is useful for order plumbing but its documented simulation omits dividends, borrow fees, market impact, latency slippage and queue position, among other limitations. It cannot by itself validate tender acceptance, distribution-heavy total returns or economic capacity. Use a separate reconciled accounting ledger, and verify actual broker corporate-action capability before an elective-offer trial. [Alpaca paper specification](https://docs.alpaca.markets/us/docs/paper-trading).

**Ideas to retain behind a smaller evidence gate**

Treasury auction pressure is a legitimate narrow research question: a July 2026 New York Fed study documents intraday supply-related effects. Test a liquid ETF translation only if suitable data already exists; the cited hours-scale finding does not establish a days-scale strategy or a standalone SPY replacement. Stop if realistic spreads or timing consume it. [Primary study](https://www.newyorkfed.org/research/staff_reports/sr1188).

Documented net index demand may be worth revisiting after the ownership infrastructure exists. Blanket index deletions and fund-fire-sale baskets are lower priorities: published work finds a diminished index effect and contamination in a widely used fund-pressure measure. [Index-effect evidence](https://www.nber.org/papers/w30748), [fund-pressure reexamination](https://onlinelibrary.wiley.com/doi/10.1111/jofi.12962).

Tax-aware indexing is a separate after-tax track, conditional on the account and usable losses. Compare terminal after-tax wealth including full liquidation, household wash sales, fees and tracking error; tax deferral must not be labeled pretax trading alpha. [Direct-indexing research](https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/AQR-The-Tax-Benefits-of-Direct-Indexing.pdf?sc_lang=en), [IRS Publication 550](https://www.irs.gov/publications/p550).

Generic option-selling income, highly leveraged carry, larger general forecasters and a renamed five-day reversal are outside the first batch. They either require a substantially different execution/data stack or fail to address what the existing tests found. Conventional value/momentum and cross-asset trend remain useful registered comparison candidates from the prior discussion; they should not be presented as novel findings of this roadmap.

**First implementation instruction**

Start stage 0 and the pure F1 baseline. In parallel, test whether public cash-event holdings and tender outcomes are sufficiently complete to support O1 and T1/T2. Deliver a small audited corpus, a frozen experiment protocol, an explicit data-gap list and the first continuous historical comparison. Do not begin with a large language-model training job or a new dashboard. Let the first empirical result determine which model and product work follows.
