# Broader discovery and frozen screening recipes

Research → Opportunity inbox now supports an explicitly captured SEC directory,
exchange filters, alphabetical batches of 50/100/250/500 symbols and reusable
screening recipes. The directory capture is a current ticker-to-issuer mapping,
not a complete market, a common-stock list, a historical universe, or a broker
tradability declaration. Its original bytes, retrieval time, normalized entries,
counts and exclusions are preserved and downloadable.

Conflicting mappings are excluded rather than choosing an issuer. Duplicate
identical entries are collapsed. Unreported exchanges remain explicitly labeled.
The currently observed directory includes common shares, units, warrants, funds,
and other securities. Company evidence must establish instrument classification;
a directory match alone does not do so.

Choose a directory batch, inspect the basket and financial thresholds, name a
recipe, and save it. A saved recipe preserves the exact deduplicated symbols,
criteria, directory membership and artifact hash. Each new run uses that same
recipe, collects fresh company evidence one company at a time, and retains the
existing explanations for threshold checks, changed fundamentals and recent
filings. The collected SEC CIK must match the recipe's saved CIK before the
candidate is admitted to the scan's results. Gaps and collection failures stay
visible. The same issuer may have several distinct securities in a batch.

Manual baskets and recipes remain available; they are explicitly not verified
against a directory. Each scan is limited to 500 symbols and shows the exact
selected count, processed count, results and failures. A 50-symbol batch is not
presented as a scan of all 10,000-plus directory entries. Results render 25 per
page and retain their evidence and disposition actions.

Stop waits for an in-flight read to settle. Resume continues only the unprocessed
suffix; it does not retry failed or completed symbols or replace prior snapshots.
An interrupted scan stays stopped after service restart until explicitly resumed.
A competing scan, in-flight read, completed batch, or corrupted saved recipe
blocks resume. There is one collection slot and no model or trading action here.

New routes under `/api/discover/opportunities`:

- `GET /catalog`: saved directories and recipes.
- `POST /universes`: explicit SEC directory capture.
- `GET /universes/{id}?exchange=NYSE&offset=0&limit=50`: bounded directory page.
- `GET /universes/{id}/evidence.json`: normalized directory and source receipt.
- `POST /recipes`: freeze name, symbols, thresholds and optional directory ID.
- `POST /recipes/{id}/scan`: run the exact preserved recipe.
- `GET /recipes/{id}/evidence.json`: integrity-checked frozen recipe.
- `POST /scans/{id}/resume`: continue a stopped scan after the current read ends.

Original source: [SEC ticker and exchange directory](https://www.sec.gov/files/company_tickers_exchange.json).

## Native verification, September 7, 2026 UTC

Browser directory capture `desk_78a9d82486ad4db8873ba3b1586b626f` contains
10,415 usable mappings from 10,415 source rows in this capture. Recipe
`desk_35eb313e81ec4d63836d2834f665694e` freezes the first 50 alphabetical
NYSE entries and the displayed criteria. Scan
`desk_7baf6f9355f046ff85d304d5bcd886ce` produced 50 results and zero failed
collections, each with its matched directory issuer identity. This does not mean
all 50 are common stocks, have complete financial facts, or pass the screen.

Browser stop and resume preserved all 19 previously completed company snapshots.
Both result pages were inspected, the directory and recipe export hashes checked,
and the completed scan compared byte-for-byte as JSON after a service restart.
The saved recipe reopened in the browser. Native evidence is in
`.research-artifacts/discovery-verification/verification.json` with associated
source, recipe, scan and screenshot artifacts. A preliminary three-symbol manual
recipe created during browser verification was not run; its displayed count and
manual membership status remain accurate regardless of its test name.

59 focused backend tests passed across discovery, opportunities, historical
replay, briefs, challenges and evidence review. The frontend test suite, cold
TypeScript check and production build passed. The exact approved paper schedule
hash and trial-plan hash were unchanged.
