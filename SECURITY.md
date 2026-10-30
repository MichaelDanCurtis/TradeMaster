# Security

## Supported use

TradeMaster is experimental, single-user, local software. Use the latest main branch
and its locked dependencies. Bind the web app and API to 127.0.0.1. There is no
multi-user authentication or authorization boundary: room headers are workflow
controls, and local clients can call administrative endpoints. Do not expose the
application to the internet, a shared LAN, or an untrusted reverse proxy. Only open
trusted sources and configure trusted provider endpoints. Model-generated advice
and imported documents are untrusted inputs.

API keys and OAuth credentials belong in environment variables or an OS secret store.
They must not appear in commits, reports, logs, issue attachments, or browser bundles.
Private databases, account reports, downloaded models and research captures stay local.
Docker build contexts exclude these files. Ignore rules do not remove files already
committed: scan both the working tree and Git history before publishing.

Paper trading uses separate credentials and explicit order review. An authenticated
paper broker connection does not grant permission to submit orders. This public release
does not establish readiness for live-money trading or shared hosting.

## Report a vulnerability

Use this repository's GitHub Security tab to report privately when private vulnerability
reporting is enabled. Do not put credentials or exploit details involving private accounts
in a public issue. Revoke and rotate any accidentally exposed credential with its provider;
deleting the current file does not remove historical exposure.

## Publication checks

The publication review scans the complete reachable Git history and release tree with
Gitleaks, checks known local credential values without printing them, audits locked npm
and Python dependencies, and runs automated tests. These checks reduce risk but are not
a penetration test or a guarantee that every vulnerability has been found.
