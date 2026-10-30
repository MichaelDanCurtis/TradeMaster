# Historical filings and Astra replay

Open **Research → Opportunity inbox → New historical replay**. The new default
uses historical filings and an Astra assessment. Existing price-only replays keep
their original behavior, and price-only remains an explicit creation option.

At each step, collect the historical packet, ask Astra to assess it, then save a
written research decision to reveal one more session. The server requires the
completed, validated model receipt to match the exact packet and step. A stale,
pending, invalid or foreign assessment cannot authorize a reveal. The decision
receipt includes the packet and model receipt hashes before the cursor advances.
The next step requires its own dated evidence and assessment.

## Historical source contract

- SEC current ticker metadata supplies only an issuer discovery hint. The original
  historical inline-XBRL filing must confirm both the requested ticker and CIK.
  Current names, metrics, company-facts aggregates and later filing descriptions
  are excluded from the model packet.
- A five-year index search reads the recent submission list and up to ten relevant
  historical index pages. The latest eligible 10-K, 10-Q and 8-K are selected;
  where the latest is an amendment, its preceding family filing is also selected.
  Coverage failures are reported, not interpreted as an absence of filings.
- Availability uses an explicit next-day rule: SEC filing date must be strictly
  earlier than the decision date. Same-day filings are excluded. This intentionally
  does not assert intraday public availability from ambiguous timestamp conventions.
- Original document bytes are retained by hash. Whole-entity USD financial facts
  come directly from supported inline XBRL contexts, tags, units, scales and signs.
  Dimensioned contexts, unsupported formats and conflicting duplicate values are
  excluded. Periods, filing dates, accessions and tags remain attached to values.
- Latest reported periods and comparable prior-year periods are shown. Free cash
  flow is derived only when operating cash flow and capex share a filing and period.
  Missing supported facts remain gaps; no current TTM replacements are inserted.
- Up to two 99-series exhibits are resolved using the original exhibit table,
  regardless of filename. Only same-accession SEC HTML links are accepted. This
  supports earnings releases with names such as `q1fy24pr.htm`.
- Only source excerpts, selected facts and already-visible closing prices reach
  Astra. Source-index receipts stay local. The ZIP export contains the packet,
  model receipt and original selected filing documents, not hidden future bars.

This is a reconstructed research rehearsal, not a point-in-time qualified dataset
or blind holdout. Documents and split-adjusted prices were retrieved later; source
revisions, current-symbol selection and model-training hindsight remain possible.
Ticker confirmation does not prove uninterrupted historical listing/share-class
continuity. Narrative excerpts are bounded selections, not a full filing review.
Management outlook must be understood as a projection made at that time, not an
observed future result. Price changes are not simulated trading profits.

## Runtime and persistence

The existing brief service supplies Codex subscription dispatch, a shared single
active slot, source-citation validation, deadlines, usage receipts and explicit
retry behavior. Historical briefs remain separate from ordinary present-day briefs
and thesis challenges. Collection can be retried explicitly after failure or
interruption. No new trading permission, order, automatic model call, or source
substitution is added. Metadata uses `replay_evidence` desk records; frozen packets
and decision receipts use the existing opportunity artifact store.

SEC source contracts: [Submissions and XBRL APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

## Native verification, September 7, 2026 UTC

The NVDA June 1, 2023 replay `desk_7fcaae895ee64dd58dcdd1bd106a4289`
completed Astra assessment `brief_14649a2e76094b7e808dcff5492be516`. Its
packet `9877240609fffdd5783e1a1cebefe69d916b8bfb1a381d9d18aecbde6c489821`
contains five original documents, seven sources including visible prices, and
nine numeric facts. The model distinguished management guidance from realized
results and repeated company guidance from independent confirmation.

The browser opened a citation into the earnings-release excerpt, saved an
explicit workflow-verification decision, revealed exactly June 2, and reopened
the completed replay after navigation. The archive's five document hashes and
packet hash were independently checked. Model prices ended at June 1; the
immutable decision receipt links the exact assessed packet before reveal.
Fifty focused backend tests passed. Native artifacts and the ZIP are under
`.research-artifacts/historical-evidence/`; `native-verification.json` records
the identifiers and checks. This verifies the research workflow, not predictive
performance or investment returns.
