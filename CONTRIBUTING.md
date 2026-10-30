# Contributing

Use a branch and a pull request. Install from the lockfiles using the README instructions.
Keep changes focused and include tests for changed behavior. Run the Python and frontend
tests and production build before requesting review.

Never commit real credentials, OAuth auth files, provider responses containing private
account data, SQLite files (including journals/WAL files), agent transcripts, or model
weights. Use clearly synthetic fixtures. Run `gitleaks git . --redact` and scan newly
added files before pushing. The CI secret scan covers both history and the checkout.

Preserve source dates, evaluation boundaries, transaction costs, and benchmark definitions
in research changes. Do not describe backtests or paper fills as proof of future returns.
Keep credential-free tests offline; external-provider or broker tests require explicit
operator configuration and must never submit orders from CI.
