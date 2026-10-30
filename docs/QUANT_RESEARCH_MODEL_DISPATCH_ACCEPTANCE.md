# Bounded model dispatch acceptance

2026-09-04. Software milestone within the active [implementation plan](QUANT_RESEARCH_BUILD_PLAN.md). This verifies the research provider boundary using local HTTP servers. It establishes no market edge, actual provider entitlement, or broker readiness.

## Implemented behavior

- Provider Settings now include research-designer and research-extractor roles, with model tier/override selection. Missing new assignments inherit the existing research provider when upgrading. Existing assignments are preserved. The designer role is routing infrastructure; an autonomous strategy-design workflow is not implemented by this milestone.
- The extractor resolves the enabled provider, actual API model ID, endpoint, credential reference and existing developer-mode policy. Strategy revisions pin a fingerprint of those settings plus prompt/schema hashes. Changes require a new revision before dispatch. A desktop model label is not substituted for an API model ID.
- A frozen plan explicitly enables new calls and declares the maximum call count, input/output token bounds, per-call timeout, token-price assumptions, price reference and historical/actual-arrival timing. The absence of this policy makes no new calls. Synthetic fixture plans use preserved responses.
- The worker enumerates eligible source packets before calling a provider. Too many packets or an oversized packet fails before selecting a partial set. Preserved exact responses are reused, including failures and unfavorable classifications. Current-source packets do not include human labels.
- Each call is durably reserved and charged against the shared family budget before its process starts. Concurrent reservations cannot spend the same remaining budget. Requested model/source/policy identity and terminal receipts are immutable. Dispatch occurs at most once for the same reserved request within an experiment; retrying an interrupted worker cannot resend it.
- A child process receives only the selected credential through private stdin. Credentials do not enter command arguments, evidence artifacts, the database or the subsequent offline replay environment. SDK retries are disabled. Runtime and output limits are enforced by the parent, which can terminate a cancelled call.
- Provider receipts retain reported model identity, exact response text, token usage, configured-rate cost, validation failures, timing and content hashes. Missing usage or ambiguous completion retains the full reservation. A response exceeding the declared bounds remains inspectable, charges its reported token usage at the frozen rates, and stops subsequent dispatch in that experiment.
- Original snapshots remain immutable. New receipts produce a separate evaluated dataset artifact; the report links every call, receipt and ledger charge. Failed or cancelled experiments retain their model-attempt history. The receipt API checks experiment membership and artifact integrity even when no final research report exists.
- Research can select/pin the configured model, explicitly enable calls in a plan, show the call authorization when queueing, and inspect individual receipts and charges. New calls remain off by default. Small nonzero costs and return effects no longer round to zero in the comparison table.

## Provider scope and price semantics

Native OpenAI uses the Responses API with `max_output_tokens`; OpenAI-compatible providers use Chat Completions with the SDK's output cap; Anthropic uses Messages with `max_tokens`. All three paths were exercised through the installed SDKs against local HTTP servers, including original-text preservation and actual model/usage metadata. Anthropic API base URLs use the root endpoint; OpenAI-compatible bases commonly include `/v1`.

The existing OpenAI-compatible routes for xAI, DeepSeek, Qwen, GLM, Ollama and OpenRouter are selectable. Their real remote deployments were not exercised here. Desktop OAuth, Google and Azure protocols report that a bounded extraction adapter is unavailable instead of silently switching providers. In particular, the existing desktop OAuth adapter strips output token caps and cannot meet this dispatch contract.

Costs are estimates from operator-frozen token rates, **not verified provider invoices**. The operator must supply suitable rates for the selected model and token categories. Input reservation uses a conservative text-byte allowance plus message overhead; reported usage is checked against the bound. A nonconforming remote provider can still bill beyond the estimate: the software records the excess and stops further dispatch rather than falsifying the charge. No remote provider was billed during this acceptance.

Historical classification remains exploratory because model training contamination is uncontrolled. Actual-arrival mode preserves real completion timing; an output arriving after an evaluation period cannot be used inside it. Genuine prospective collection and independent label coverage are still separate requirements.

## Verification

The focused dispatch suite passes **14 tests**. It covers Chat Completions, native Responses and Messages round trips, output caps, credential isolation, concurrent/idempotent reservations, shared family exhaustion, provider changes, no automatic retry after an HTTP error, cancellation during a live request, crash/restart ambiguity, candidate overflow before billing, missing metadata, token overruns, terminal immutability, and failed-experiment receipt integrity.

Commands from the repository root:

```sh
.venv/bin/python -m pytest tests/research/test_dispatch.py -q
.venv/bin/python -m pytest tests/research tests/test_role_models.py tests/ui/test_provider_registry.py tests/ui/test_repository.py tests/ui/test_room_policy.py -q
```

Final combined result: **144 passed in 24.73 seconds**. Logs: `/tmp/trademaster-dispatch-focused.log` and `/tmp/trademaster-dispatch-regression.log`. The native serialization test intentionally uses an unknown test model ID, producing one expected advisory warning. The provider catalog test was aligned with the already-implemented Copilot adapter's available status; no production availability was changed for that assertion.

Production `npm run build` passes. The four previously recorded lint warnings remain. Targeted role-model/Settings tests pass **11 tests**. The full frontend suite remains **154 passed, 6 failed**, with the same older source-text assertions recorded in implementation status; it is not release-green. Logs: `/tmp/trademaster-dispatch-build.log`, `/tmp/trademaster-dispatch-webtests.log`, `/tmp/trademaster-dispatch-full-webtests.log`.

## Browser acceptance

The production UI used isolated database `/tmp/trademaster-dispatch-ui/ui.db`, artifacts `/tmp/trademaster-dispatch-ui/dispatch-artifacts`, and a local fake provider. API real committee runs and dotenv loading were disabled. A clearly labelled synthetic source was assigned a test-only historical manifest solely to exercise the non-fixture dispatch path; it is not genuine historical evidence.

The operator flow created a hypothesis, selected the labelled guidance universe, pinned the configured test provider, froze three matched versions, and froze a plan with one allowed call, 32,768 reserved input tokens, 2,048 output tokens, $1/$2 per-million test rates, and a $20 family budget. It queued the 2020 holdout, ran the worker, and inspected the automatically displayed report and model receipt. Keyboard focus/Enter/Space worked for the controls.

- Strategy: `strategy_77b9fcbafe694031ad5b794979c118c1`.
- Experiment: `exp_fa8840c1b2634bd08d6afd9e758df4df`.
- Report artifact: `90c0c63f1893cf928e083c18965bdad3dba057986c56cb3f10d3105f3c558064`.
- One HTTP request for the browser-created experiment; a separate seeded experiment also made one request. No retries were sent.
- Initial reservation $0.036864; recorded charge $0.000300 from 100 input and 100 output tokens at the test rates.
- All three variants remained `insufficient_evidence`. The model arm's small negative incremental result after extraction cost remained visible.
- Reloading the rebuilt production UI retained the completed report and fetched the preserved receipt. No research alerts, JavaScript exceptions or framework error overlays were present. The 637-pixel receipt panel fits within its 683-pixel main column.
- Screenshots: `/tmp/trademaster-dispatch-ui/policy.png`, `final-comparison.png`, `final-receipt.png`. Records and the local-request log are in the same directory.

The browser, test API, web server and local model server were stopped after acceptance. No broker orders, funded deployments, purchases or paid model calls were made.

## Remaining release work

The full LEAN adapter and shared-function parity, simple equity reference, genuine data/entitlement coverage, prospective observations, independent labels and calibration/event-outcome audit remain. So do paper-review/promotion, deployment reservations and recovery, exact final-quantity broker checks, real accounting/reconciliation, the full release walkthrough, and a separately approved provider-backed paper smoke. The overall implementation goal remains active.
