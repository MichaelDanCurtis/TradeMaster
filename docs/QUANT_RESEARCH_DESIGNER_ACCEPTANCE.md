# Strategy designer acceptance

Date: 2026-09-05. This records one implementation increment in the active full build plan.

## Implemented behavior

Research can request one model-assisted proposal for a saved hypothesis, using the configured `research_designer` role and its actual API provider/model configuration. The operator reviews the universe, risk constraints, family trial/cost ceilings and declared token prices before dispatch. The request preserves the saved draft revision, brief, full prompt/schema, configuration fingerprint and immutable request hash.

The response contains a hypothesis, economic mechanism, falsification tests, required data, failure modes and implementation notes. Supported output contains a validated trend or numeric guidance specification. Unsupported ideas and abstentions have no executable specification. An invalid schema, changed template/universe/risk policy, tool request, unconfirmed model identity or metering violation cannot produce an applicable proposal. These checks do not establish the truth of model-generated prose; the UI labels every proposal unevaluated.

Each attempt consumes one family trial and reserves its maximum declared charge before provider dispatch. Experiment queueing, compute reservations and extractor reservations include designer charges. A later plan cannot reset the family's limits. Verified usage adjusts the charge; unavailable usage or an interrupted call retains its reservation. A metering overrun stops further model calls in that family. Charges remain configured estimates rather than invoices.

The provider call runs once in a separate process, with no tools and SDK retries disabled. Only the selected credential travels through stdin; the child environment excludes other provider/broker credentials and dotenv loading. The API allows a provider timeout of at most 60 seconds, a bounded parent wait and process termination, four active designs globally and one per hypothesis. Immutable terminal receipts and an exclusive dispatch transition prevent duplicate requests from becoming duplicate calls. Expired requests recover as unknown on inspection or dispatch, retain charges, and never automatically resume. Late results cannot replace a terminal receipt. This does not claim that a remote provider cancels its own work when the local process stops.

The review UI keeps model output separate from saved hypotheses and frozen versions. The operator can edit and explicitly save the hypothesis, edit the proposed specification, then freeze it with a link to the original design ID and request hash. Guidance review requires inspection of the configured evidence classifier and freezes all three matched arms. The existing independent test-plan, evaluation and paper-review boundaries remain in force. No design request grants trading authority.

## Verification

- Final backend regression: **395 passed, 12 explicit native-integration skips**, in 91.82 seconds. `/tmp/trademaster-designer-finalregression.log`.
- Focused designer and run-publication suite: **29 passed**. `/tmp/trademaster-designer-finalfocused.log`.
- Frontend suite: **160 passed**. `/tmp/trademaster-designer-webtests.log`.
- Production build passed with the four previously recorded warnings in other components. `/tmp/trademaster-designer-webbuild.log`.
- Python compilation and changed-file whitespace checks passed.

The backend cases exercise the actual provider SDK against a localhost HTTP server: durable precharge before transport, exact responding model, tool-free request, secret isolation, one dispatch under concurrency, idempotent recovery after configuration drift, malformed/unsupported/abstaining output, immutable requests/receipts, shared experiment budgets, stale drafts, expired requests, provider errors without retries, token overruns, room authorization, and explicit version provenance. A child that ignores the SDK timeout is terminated by the parent and leaves an unknown receipt with the full reservation.

Regression testing also exposed an existing completion-publication race in the symbol research runner. Final trace metadata and run status now persist before `run.completed` is published. A deterministic publication-time assertion covers the ordering. Two simulated-run tests now explicitly select simulated execution instead of relying on an obsolete default.

## Browser evidence

The isolated app used `/tmp/trademaster-designer-ui/designer.db`, localhost model transports and synthetic output. No paid provider, broker submission, genuine market data or performance experiment was involved.

The trend flow reviewed the actual configured model and declared cost, made one design call, inspected the proposal, saved a reviewed hypothesis, rejected an unsupported edited rule, and froze a human-edited volatility window of four sessions while the original model receipt retained three. After rebuilding and restarting both app servers, the design receipt, frozen version and the family ceilings of 30 trials/$10 remained visible. The plan editor retained and disabled those frozen family budget fields.

The guidance flow requested one proposal, saved the reviewed hypothesis, verified that freezing before classifier review was rejected, reviewed the actual classifier, and froze the guidance-only, numeric-quality and Astra-challenger arms together. Reload retained the receipt and all three versions. Both final browser sessions reported no JavaScript errors; the changed flow had no unexpected alerts or horizontal overflow.

Direct database verification found two completed design attempts, four frozen versions, the preserved human edit, a shared design ID across the three guidance arms, and a configured charge of $0.000300 per design. This is synthetic metering evidence, not a paid invoice.

Artifacts: `app.py`, `guidance_app.py`, `references.json`, `guidance-references.json`, `verified-state.json`, `provider-requests.json`, `guidance-provider-requests.json`, and screenshots (`initial.png`, `requested.png`, `frozen.png`, `rebuilt.png`, `guidance-frozen.png`) under `/tmp/trademaster-designer-ui/`. Test browsers and app servers were closed after acceptance.

## Status boundaries

- Software: bounded, reviewed strategy design is implemented and locally verified; the entire release walkthrough remains active.
- Research: proposals and source requirements are unevaluated. Genuine datasets, entitlements, calibration and prospective acceptance remain outstanding.
- Broker paper readiness: unchanged by this feature. A model proposal cannot activate a deployment or approve/submit an order.

The remaining full-plan work is tracked in [implementation status](QUANT_RESEARCH_IMPLEMENTATION_STATUS.md).
