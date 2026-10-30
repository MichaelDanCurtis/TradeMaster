# Evidence review in Research Explorer

Request a research brief for a ticker in Research → Research explorer. The review
uses the existing Codex subscription adapter and preserves its one-call, bounded,
tool-free behavior. It collects dated quotes/news and includes previously saved
company evidence and a recent forward Forecast Lab result when available.

New briefs have a version-2 evidence inventory:

- Included/missing source categories and publication/retrieval ages frozen at collection.
- Unknown publication dates remain unknown. Company snapshot retrieval is no longer
  presented as publication. Invalid/future timestamps are excluded with a gap.
- Exact source fingerprints, a complete packet hash, and a system/schema hash.
- Historical close, 20/50-session SMA, 20-session price return, and annualized realized
  volatility calculated from the saved forecast's 256-session context. Forecast paths
  and future outcomes are never inputs to these calculations.
- Model forecasts and indicators carry the same origin when derived from the same
  saved experiment. The display explains that they are not independent confirmation.

Astra can return agreement, tension, or non-comparability checks. Each is explicitly
an interpretation, must cite two distinct preserved sources, and shares the existing
25-word per-source quote budget across the entire brief. Dates, units, price basis,
forecast horizons and repeated news coverage must be considered. Exact excerpt
validation establishes citation integrity, not that an interpretation is correct.

Older briefs remain unchanged and display without the new inventory. Download
**evidence and review JSON** to preserve the packet, model output, model identifier,
and hashes. Export refuses a packet whose stored hash no longer matches.

## Scope and next evaluation

The review supports numerical/text evidence and optional PNG, JPEG or PDF uploads.
It does not perform continuous screenshot capture or specialized chart OCR. It does not claim
SHAP attribution, a calibrated combined confidence score, sentiment-model execution,
or a proven investment advantage. The existing paper scheduler is unchanged.

Before introducing visual evidence, freeze a paired evaluation with:

1. The same symbols, decision times and preserved numerical source packets in both arms.
2. A numerical-only arm and an enriched arm, with every source available before its
   decision cutoff; record retrieval/version timestamps rather than reconstructing
   past availability from publication dates alone.
3. Identical model revision, prompt/schema version and inference settings; retain
   all attempts, including failures and abstentions.
4. Predefined checks for supported citations, factual errors, incorrect comparisons,
   missing-evidence detection, latency and usage. Review outputs without arm labels
   where practical. More fluent writing is not evidence of better forecasts.
5. If testing predictive or trading value, specify a separate fixed forecast or
   deterministic paper strategy, baselines, costs and held-out decision dates before
   collecting outcomes. Neither this review nor current pending paper results prove
   an edge.

## Selected image and PDF evidence

Enter a ticker, choose a file and (for PDFs) explicit page numbers, then choose
**Prepare attachment locally**. Review the page previews before **Write brief**.
Preparation makes no model call. Writing sends only selected rendered images,
selected embedded PDF text, and the assembled research packet through the existing
Codex ChatGPT connection. The original PDF file is not sent to the model.

Limits: two files, four pages/images total, 10 MB per file, static PNG/JPEG below
20 megapixels, PDFs up to 500 pages, selected page numbers only (e.g. `1,3`). Password-
protected/unreadable PDFs and unsupported images fail explicitly. Rendering runs in
a disposable process with a 25-second timeout; originals are retained only after
successful preparation. A lock limits native rendering to one process at a time.

Pillow 12.3.0 and pypdfium2 5.13.0 are pinned dependencies. The renderer keeps aspect
ratio, applies EXIF orientation, composites image transparency on white and caps the
long edge at 1800 pixels. Original bytes, selected page PNGs, renderer versions,
renderer hash, dimensions and selected-page text are saved with SHA-256 fingerprints.
PDF text extraction is not OCR and may omit/misorder chart text. Other pages are not
represented as reviewed. User-declared document dates and ticker associations remain
unverified; upload time is not represented as publication time.

The installed Codex app-server protocol was inspected and its `localImage` input
verified in a real gpt-6-astra call. The adapter writes prepared PNG bytes to its
temporary directory and labels each image with its source ID. It never accepts a
caller-supplied filesystem path or arbitrary image URL. Existing no-tool permissions,
model identity checks, timeouts and no automatic retry remain in force. Model input
images are removed with the temporary directory. Observed input-token thresholds add
8192 per supplied image; these are review thresholds, not guaranteed subscription caps.

Visual citations use a page/source ID and a human-readable region. They must be
interpretations and cannot masquerade as exact text citations. Exact text citations
still require matching preserved excerpts. This validation proves reference structure,
not visual correctness, chart identity, calibrated confidence or investment value.

Download the review JSON, individual originals, or **review with original attachments**
ZIP. The ZIP includes `review.json`, attachment manifests, and original/rendered bytes
under their SHA-256 filenames. Source and attachment integrity failures refuse export.

Qualification used a clearly marked synthetic, two-page PDF. A real image-only Codex
call recovered its three bar labels (20, 40, 30) and correctly identified it as synthetic.
Automated tests cover selected-page exclusion, corrupted files, invalid dates/pages,
upload limits, ticker binding, visual citation rules and temporary image cleanup.
That verifies the plumbing; it is not a broad chart-reading accuracy benchmark.

On 2026-09-06 the browser upload → local preview → Codex review → saved-source
workflow completed for the synthetic TEST fixture. Brief
`brief_dfdf79d691c241bcac3acdbe4227a870` correctly declined to infer an investment
thesis from synthetic data. Its image receipt matched the selected page's hash;
the downloaded ZIP preserved the original PDF byte-for-byte and excluded page 2
from the model packet. Archive object and packet hashes verified. The existing
approved paper schedule's content hash remained unchanged. Validation passed
176 Python tests, 163 frontend tests, TypeScript checking, and the production build.

Specialized chart detectors should be introduced only if measured extraction failures
justify them. Prefer underlying market data for exact numerical calculations.
