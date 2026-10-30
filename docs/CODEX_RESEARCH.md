# Codex research integration

Implemented September 5, 2026. The research designer and evidence extractor can use Codex App Server with managed ChatGPT authentication. The existing Codex OAuth provider remains assigned; the research path now launches the supported Codex runtime instead of directly using its backend endpoint. Other legacy graph roles retain their existing adapters.

## Runtime and identity

An explicitly configured absolute `codex_binary` takes precedence. Otherwise, the local desktop runtime is preferred when installed (`/Applications/ChatGPT.app/Contents/Resources/codex`), with the CLI on PATH as fallback. The runtime binary path, size/modification time, adapter source hash, Codex home and selected model form the provider pin. A changed pin requires a new reviewed request/version. ChatGPT authentication and exact model availability are checked before a turn starts; API-key fallback and model substitution are rejected.

Local discovery confirmed desktop Codex 0.153.3 exposes `gpt-6-astra` for the user's ChatGPT account. The older PATH CLI 0.142.5 reported a different catalog. Only the `research_designer` and `research_extractor` model overrides were changed to `gpt-6-astra`.

## Research boundary

Each request runs as one ephemeral turn in a temporary directory. Process overrides disable MCP integrations, apps/plugins, hooks, shell/exec, browser/computer controls, memory, goals and delegation. A named permission profile allows minimal platform reads and the temporary directory, with no tool network access or filesystem writes. The server must confirm this profile and the no-approval policy. All MCP servers in the effective configuration must be disabled before sampling. Unexpected server approval requests are rejected and unexpected tool items invalidate the result. Broker credentials and API keys are excluded from the process environment.

The source packet is supplied as untrusted input. Original application schemas and validators remain authoritative. A separate strict wire schema expands defaulted properties and converts discriminated unions for Codex structured output. Proposals remain unevaluated; Codex cannot freeze a strategy, promote evidence, fund a deployment, approve a baseline, or submit an order through this interface.

No persistent Codex task is created. The user's Codex configuration is not edited. Codex continues to own its normal login/refresh lifecycle.

## Subscription policy

`ExtractionPolicy.billing_mode` is `api_metered` by default for compatibility. Codex requires explicit `codex_subscription` review and zero API token rates. Other providers reject this mode. Existing trial counts, one-attempt idempotency, timeouts and frozen research-family accounting remain in place.

Subscription attempts record actual input/output token usage and `subscription_usage` as their cost basis. Zero in API cost accounting means no per-call API invoice is estimated; it does not mean free/unlimited subscription usage. Subscription allowance and purchase price are not converted into fictional token prices.

Input/output token thresholds are review thresholds, not provider-enforced caps. When reported usage exceeds a threshold, the response is invalidated, interruption is requested and subsequent family dispatch is blocked. Usage can exceed a threshold before interruption takes effect. Missing usage invalidates evidence. Local lifetime and protocol/output byte bounds are enforced separately. A failed or interrupted attempt remains in history and is not automatically retried.

## Verification

The native desktop Codex process returned a structured `gpt-6-astra` response through ChatGPT authentication, then completed a full strategy-design request through the killable designer child and durable repository. The successful full receipt recorded 8,394 input tokens, 1,047 output tokens, no validation errors and subscription usage. This is provider-backed design output, not measured investment performance.

Isolated integration development retained earlier failed attempts; an invalid strict schema was corrected, not hidden by deleting or relabeling receipts. Automated tests cover authentication rejection, model availability, disabled MCPs, strict-schema translation, forbidden tools/approvals, rerouting, missing usage, cross-thread isolation, output threshold handling, timeout cleanup and excluded broker environment variables, alongside the existing designer/dispatch idempotency and accounting tests.

Final acceptance: the normal application saved `Paper trial — watchlist trend` as strategy `strategy_a22875160d71409da2d734fe3ede16d8`. Its design `design_994c331466f144dcb1bec945f31a0991` completed through `gpt-6-astra` with 8,405 input tokens, 1,037 output tokens and no validation errors. Both research role assignments are accepted by Settings. The API, web build, research worker, deployment worker and scheduler started successfully. The broad backend run passed 786 tests (12 Docker-dependent tests skipped); the final Settings regression run passed 16 tests, and the final frontend run passed 160 tests. The production build passed. The first visual review was blocked by the locked Mac. On continuation, the unlocked in-app browser was refreshed and the Codex model review, subscription history, saved proposal, Settings role selectors, baseline approval and account reconciliation were verified visually. See PAPER_TRIAL_REVIEW.md for the stopped, unapproved scheduler preview and remaining live paper-execution checks.

Official references: [Codex App Server](https://learn.chatgpt.com/docs/app-server), [authentication](https://learn.chatgpt.com/docs/auth), and [configuration reference](https://developers.openai.com/codex/config-reference). The installed runtime's generated protocol schema was used to resolve version-specific permission-profile behavior.
