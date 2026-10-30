# News evidence and quantitative research

The working September 7 pilot is in
`.research-artifacts/news-signals-2026-09-07/report.md`.
This is an offline research pipeline, not a new live dashboard or trading rule.
It uses the configured Alpaca market-data connection and local FinBERT inference;
it requires no new hosted AI API account. Codex research agents can supply cited
event interpretations through the separate validated evidence contract.

## Implemented path

1. `scripts/research/capture_news_signals.py` collects paginated Alpaca/Benzinga
   news into a fresh directory. It stores raw responses, request parameters,
   receipt timestamps and SHA256 hashes. Failed and truncated captures are explicit.
2. `scripts/research/build_news_signals.py normalize` rejects malformed dates,
   identities and source links. Article revisions remain distinct. Unsupported
   ticker tags quarantine the entire article; they do not become guessed mappings.
3. `score` runs pinned `ProsusAI/finbert` locally on CPU or Apple MPS/Metal.
   It measures headline tone only for single-ticker articles. Multi-company
   articles remain in activity counts but abstain from the tone score.
4. `tradingagents/research/news_signals.py` produces dated numeric snapshots:
   article count, exact normalized headline clusters, missing/classified counts,
   positive/negative/neutral counts, signed text tone and latest-availability age.
   It retains article IDs so every number can be traced back to source evidence.
5. `validate_agent_evidence` checks a bounded event schema with exact supporting
   spans. `agent_snapshot` separately counts earnings/guidance, financing,
   legal/regulatory, commercial, management and other events, plus qualitative
   direction. Unknown financial direction remains missing, not neutral or bullish.
6. `scripts/research/evaluate_news_signals.py` runs the frozen historical
   association diagnostic and replays every earlier snapshot without future rows.

Publication, revision, local receipt and inference completion are distinct.
Observed snapshots require all relevant timestamps plus a declared latency.
Historical provider-current-version text uses `max(created_at, updated_at)` plus
15 minutes and remains explicitly a **retrospective proxy**. A web agent fetching
an old page today cannot backdate it: `normalize_web_excerpt` permits observed
mode only. Day-precision publication dates retain their precision and use the
following UTC day as a conservative convention; no release clock time is claimed.

Exact normalized headline repetitions within 24 hours collapse only using
available rows. This is not semantic event deduplication. Different websites do
not establish independent sources; Alpaca/Benzinga is one distribution family.
Endpoint pagination completion is distinct from archive completeness, valid
issuer mapping and coverage of any arbitrary decision window.

## Commands

From the TradingAgents checkout, use a **new** capture directory:

```sh
.venv/bin/python -m scripts.research.capture_news_signals \
  --root NEW_CAPTURE_DIRECTORY --symbols AAPL,JPM,XOM,UNH \
  --start 2024-01-01T00:00:00Z --end 2024-02-01T00:00:00Z
.venv/bin/python -m scripts.research.build_news_signals normalize --root NEW_CAPTURE_DIRECTORY
.venv-forecast-challengers/bin/python -m scripts.research.build_news_signals score \
  --root NEW_CAPTURE_DIRECTORY --device mps \
  --revision 4556d13015211d73dccd3fdd39d39232506f3e43
.venv/bin/python -m pytest tests/research/test_news_capture.py tests/research/test_news_signals.py -q
```

Capture and derived evidence refuse overwrite. `snapshot` accepts an explicit
cutoff and defaults to observed mode. Its standalone CLI conservatively marks
coverage incomplete until the caller checks query bounds and rejected rows.
The historical diagnostic uses `protocol.json` and `diagnostic-lock.json`, which
bind the universe, period, model, source inputs, code, price panel and actual
market calendar. It refuses changed dependencies. Reproduction should use a copy
of the saved run with the two derived diagnostic output files absent; retain the
original evidence and both locks. No model retraining is involved.

## What the diagnostic establishes

The initial sample contains 12 current tickers chosen for industry diversity,
not a survivor-free historical universe. It evaluates weekly seven-day tone
against subsequent five-session adjusted open-to-open excess return over SPY.
These are descriptive rank correlations; observations can overlap and are not
independent significance tests, trading profits or risk-adjusted alpha.

The four current web-agent examples are selected issuer announcements. They
demonstrate grounded extraction, not unbiased media coverage, return prediction
or verified market novelty. The stored publication dates make their age visible.

## Follow-on proposal closed

The subsequently completed [insider and quality test](INSIDER_QUALITY_FINAL_TEST.md)
failed, and the user approved retiring that fixed strategy on September 7, 2026.
The earlier proposal to keep extending it with quality/news combinations is
removed from active work. This news pipeline remains a research instrument;
it does not automatically reopen the retired hypothesis or authorize deployment.

Any separately authorized future news hypothesis would still need representative
issuer-specific extraction validation and causal source coverage. An announced
buyback is not completed repurchasing; positive earnings are not necessarily a
positive surprise; an upbeat headline is not a calibrated return probability.

Sources: [Alpaca historical news](https://docs.alpaca.markets/us/docs/historical-news-data),
[API date/pagination contract](https://docs.alpaca.markets/us/reference/news-3),
[FinBERT model](https://huggingface.co/ProsusAI/finbert),
[SEC API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).
