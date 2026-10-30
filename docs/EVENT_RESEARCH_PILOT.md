# Original filings and event research: first implementation

September 7, 2026, America/Los_Angeles. **The source-capture and filing-stability pilot is implemented and has run. No investment-return test has run for these new hypotheses.**

This implements the first data work in the [SPY research roadmap](SPY_OUTPERFORMANCE_RESEARCH_ROADMAP.md). The independent forward study and retired insider-quality strategy are unchanged.

**Verified results**

| Item | Result | Meaning |
|---|---|---|
| SEC source requests | 258 captured; zero HTTP failures | Exact raw responses and receipt hashes retained |
| Raw source bytes | 661,467,613 | Includes index, metadata, original reports, offer documents and holdings |
| Original filing pairs | 100, across 25 issuers and 11 descriptive sectors | The planned engineering sample was filled |
| Initial structural validation | 92 valid, eight rejected | Flat DEI extraction conflated parent/subsidiary fields in joint filings |
| Context-aware identity review | 100 structurally valid | Target issuer, reporting date and fiscal period resolved through XBRL contexts |
| Original 92 scores | Unchanged after the correction | Text normalization and Jaccard arithmetic were not altered |
| Holdings capture | Five 13F filings, 915 position rows | Raw manager-level holdings; not 915 independent companies or funds |
| Acquisition/disposition candidates | Five found, five reviewed | Four outside the all-cash shareholder-payment mechanism; one still unqualified |
| Tender source rows | 20 rows, 14 unique accessions | Bidder/target cross-listings are retained and flagged, not counted as separate offers |
| Targeted tests | 22 passing | Parsing, fiscal identity, timing, immutable capture, source tampering and context isolation |

All 100 text-stability scores are now available. Their range is approximately 0.692–0.975, with median 0.853. These numbers measure overlap between word sets. They are neither stock recommendations nor probabilities of investment success.

**What is frozen and reproducible**

The pilot first froze its protocol, code hashes, original issuer-source hash and issuer selection. It selected two distinct issuers per current sector using a fixed CIK hash, then filled to 25. The sample is deliberately labeled a current-roster engineering sample; it cannot establish historical market-wide performance.

Metadata selection was then frozen before original-document scoring: four 2024 report periods per issuer, original 10-K/10-Q filings only, with a matching form and a prior report 350–380 days earlier. Original DEI fields must confirm the same fiscal period and consecutive fiscal years. Amended reports are not substituted for originals.

The text baseline removes tables, hidden XBRL, scripts and styles; it measures Jaccard similarity of lowercase word sets after a fixed stop-word list. An unsigned similarity score does not identify whether a change was good or bad. The full original filing remains the text unit, including co-registrant narrative where present.

Historical availability conservatively uses the later of acceptance time and the end of the stated filing date in New York, followed by a five-minute processing delay. The timing helper requires a supplied exchange calendar and two complete subsequent trading sessions before entry. Forward use separately requires actual receipt and extraction completion. Current retrieval timestamps never establish historical availability.

The eight initially rejected pairs belonged to Con Edison and Corteva joint filings. An additional, separately versioned identity review binds DEI fields to the target issuer's non-dimensional XBRL context at the report date and respects explicitly declared numeric-date transformations. The original run, its rejection reasons and all 92 previously valid scores are preserved. No return labels were inspected to make this correction.

The independent verifier checked 464 files in the original manifest and independently recalculated the original 92 valid scores using equivalent set arithmetic. This is integrity and arithmetic verification, not a claim that another person independently audited every document's semantics. Context-review evidence and the completion manifest cover the subsequent additions.

**Cash-flow and tender findings**

The frozen small issuer sample yielded five Item 2.01 candidates, short of the planned cap of 20. The source review found:

- Emerson and Viatris disclosed cash paid to the operating company for business dispositions. This does not establish cash paid to institutional shareholders.
- Healthpeak/Physicians Realty and Amcor/Berry primarily exchanged shares. Cash in lieu of fractional shares does not turn these into all-cash takeovers.
- Lumentum/Cloud Light disclosed cash share consideration, but the target's public-security identity, historical institutional ownership and shareholder-payment timing remain unqualified.

Every review has an exact source passage, offsets into a hashed text extraction, and a link to the captured filing. None of these five is currently eligible for an O1 investment replay. This says the initial candidate cohort is insufficient; it does not test or reject the cash-redeployment hypothesis.

The five holdings filings describe December 31, 2023 positions and were filed in January/February 2024. They are manager-level observations, with raw reported values and units preserved. A proper ownership graph still needs broader holder coverage, dated security mapping, duplicate/option handling and transaction-specific recipient verification.

The tender capture includes 20 SEC master-index rows but only 14 unique filings. An offer can appear under both a bidder and a target; unique accession is only the first deduplication step, because amendments and related filings still need a transaction identity. Instrument eligibility, exchange tradability, complete amendments, final acceptance, delivery, NAV/quotes and broker deadlines remain unqualified. No tender profit was calculated.

**Historical market-data access**

The full F1 comparison still requires a qualified historical universe, lagged capitalization, tradable prices and terminal corporate-action outcomes. Using the pilot's 2026 survivors would repeat the selection problem in earlier research.

I checked the configured Finnhub credential without exposing it. The historical-market-cap and historical-index-constituent requests both returned HTTP 403. That establishes that these requests are unavailable with the current setup; it does not establish the exact reason or that every Finnhub feature is unavailable.

Sharadar's provider-published Apple demo returned HTTP 200 for daily metrics, stock prices, ticker metadata and corporate actions. Three requests contained sample records; the narrow corporate-action date range contained none. This verifies basic access and several schemas, not delisted coverage or point-in-time correctness. No account was created or subscription purchased. [Demo authentication](https://sharadar.com/docs/auth).

The provider currently lists its Full History Bundle at **$69/month**, including prices, fundamentals, daily capitalization, actions and holdings. The $29/month bundle covers five years. The full-history tier is the candidate for a broader regime test; this is market-data access, not an AI provider. Pricing and scope were checked on September 7, 2026. [Official plans](https://sharadar.com/subscribe).

Before accepting any paid feed, audit these cases and fields:

- Stable security identifiers and historical symbol/class mapping, including old versus successor Chesapeake, SIVB/SIVBQ, SBNY, and FRC/FRCB. Do not treat a metadata flag as proof of complete terminal proceeds.
- First/last price dates, delisting reason, available OTC history, and actual cash/share distributions. Explicitly record any unvalued period.
- Market-cap units and historical availability: the Sharadar daily table documents USD millions, while other tables can use different units. Confirm lagged as-reported construction against original filings; current metadata fields must not select the historical universe. [Daily table](https://sharadar.com/docs/daily).
- Total-return versus split-adjusted versus raw prices, with no double counting of distributions.
- Full historical coverage and the point-in-time meaning of revised records. The Apple demo cannot establish any of these properties for failed firms.

Norgate remains an alternative for price/history qualification, but its trial is limited to two years and its Python/updater workflow requires Windows. Its historical-membership coverage alone would not provide the historical market-cap ranking or full tender economics required here. [Trial](https://norgatedata.com/freetrial.php), [supported environments](https://norgatedata.com/accessibility.php).

**Reproduce and inspect**

Run from the `TradingAgents` checkout. Capture uses public SEC GET requests with two workers and at least 0.6 seconds between requests. An existing root cannot be frozen again; scoring and review artifacts are write-once.

```bash
.venv/bin/python -m pytest tests/research/test_filing_stability.py tests/research/test_event_research_pilot.py tests/research/test_filing_identity.py -q
.venv/bin/python -m scripts.research.event_research_pilot freeze --root NEW_PILOT_ROOT
.venv/bin/python -m scripts.research.event_research_pilot capture --root NEW_PILOT_ROOT
.venv/bin/python -m scripts.research.event_research_pilot score --root NEW_PILOT_ROOT
.venv/bin/python -m scripts.research.verify_event_research_pilot --root NEW_PILOT_ROOT
.venv/bin/python -m scripts.research.review_filing_identity --root NEW_PILOT_ROOT
```

The existing run is in `.research-artifacts/event-research-pilot-2026-09-07/`:

- `protocol.json`, `protocol-lock.json`, `selections.json`, `selection-lock.json`: frozen rules and input selection.
- `receipt.json`, `raw/`, `normalized/`, `audit.json`, `manifest.json`: original capture and baseline.
- `verification.json`: independent original-run integrity/arithmetic checks.
- `identity-review/`: separately frozen context repair, evidence and all 100 scores.
- `terms-review/`: reviewed cash-event passages and tender duplication findings.
- `completion-manifest.json`: hashes of the completed artifact set and implementation files.

Provider preflights are in `.research-artifacts/event-research-provider-demo-2026-09-07/`. Receipts omit authentication values.

Next: qualify the historical market-data source, freeze the full portfolio experiment on that qualified universe, and expand original-filing coverage. Cash-redeployment discovery needs a broader deal cohort; tenders need transaction/instrument qualification and complete outcomes. Source collection and text scoring are working. Outperformance remains untested.
