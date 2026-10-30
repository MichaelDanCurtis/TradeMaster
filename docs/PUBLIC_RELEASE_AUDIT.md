# Public release review — October 29, 2026

Scope: the TradeMaster source checkout and all reachable Git history, prepared for
publication at https://github.com/MichaelDanCurtis/TradeMaster.

## Results

- Gitleaks 8.30.1: no credential findings in history or the exact release file set.
- Known credential values from the local environment were compared without printing
  them; no matches in the release files or historical blobs. This is supplementary
  to pattern scanning and does not cover every possible secret store or token format.
- Locked npm dependencies: zero known vulnerabilities after updates and a patched
  PostCSS override. Locked Python dependencies, including development extras: zero
  known vulnerabilities after updates. These are dated advisory-database results.
- Python: 1,367 passed, 13 explicit Docker/LEAN integration checks skipped.
- Frontend: 163 passed; Next.js production build passed.
- Focused lifecycle/checkpoint tests: 5 passed.
- Bandit review: the initial medium-confidence SQL warning used only fixed table
  names and bound values. It was simplified to two fixed parameterized statements.

## Release hardening

Private account trial reports, SQLite databases/journals, environment files,
agent state/transcripts, model environments, and research captures are excluded.
Docker contexts exclude private runtime files as well. A CI index check rejects
sensitive paths; CI also scans history and checkout for credentials, audits both
dependency locks, and runs tests/builds. Upstream history, license and attribution
are retained. No credentials or private account datasets are intentionally shipped.

The web and API startup defaults bind to localhost. FastAPI background workers now
use the supported lifespan interface; cleanup runs even after a startup failure.
Python 3.11 or newer is required by the patched image dependency; Python 3.12 is
the tested setup. Research test dependencies are declared in the development extra.

## Limits

This review is not a penetration test. The application remains a local, single-user
research tool without multi-user authentication. Do not expose its API or web server
to public networks or an untrusted LAN. No live trading, provider spending, order
submission, or investment performance was validated by these tests. Optional model
weights and services require separate installation, license review and validation.
Existing private runtime environments were not upgraded or restarted by this review.
