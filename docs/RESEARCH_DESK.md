# Research desk: six connected workflows

Open **Research → Research desk** in the local product.

1. **Company evidence.** Collect current Finnhub identity and metrics, exact SEC issuer mapping, recent filing links, annual USD statement facts, and bounded filing/exhibit excerpts. The filing cover can establish a registered security description only when its table contains the exact ticker. Unknown classifications remain unknown. Every source response has a SHA-256 artifact receipt; refreshes preserve prior snapshots. Free cash flow is computed only from operating cash flow and capital expenditure with matching periods, filing dates and accessions. A saved company packet and filing excerpts feed the existing explicitly requested Codex/Astra brief.
2. **Financial screens.** Scan 1–12 explicit symbols for revenue growth, net margin, and positive annual free cash flow. Thresholds are strictly greater-than; missing or stale cash-flow facts cannot pass. This is a bounded candidate screen, not complete market coverage, a valuation conclusion, or a recommendation. Provider TTM metrics may lack a separate underlying as-of date; annual SEC facts retain their dates.
3. **Thesis monitors.** Save an investment question, written invalidation conditions, numeric growth/margin thresholds, and the company snapshot used as the baseline. The API's local worker checks due active monitors daily, one issuer per minute, while the API is running. Each review retains the previous and original snapshot IDs, changed metrics/annual facts, new filings and numeric checks. Pause/resume and manual review are available. Written conditions need human interpretation; no model, notification service, or broker is invoked by monitoring. This worker assumes the normal single local API process; it is not a distributed job scheduler.
4. **Development experiment.** Reuse the existing local replay engine and saved Astra trend proposal, with captured raw SIP bars and corporate-action/calendar receipts. The bounded experiment uses 2022 warmup and 2023 development only, six strategy/basket/cash comparisons at base and doubled costs, and a pinned copy of the rules. It retains complete requests/results, source and engine hashes, reconstruction assumptions, failed attempts and unfavorable comparisons. Successful repeated runs reuse the same content-addressed result. No strategy version is frozen, historical data admitted, holdout evaluated, deployment promoted, or order created by this workflow.
5. **Paper trial.** Read the existing trial plan and verified broker/order/accounting evidence through the same `build_report` function used by the report CLI. Future sessions remain pending. Trial-owned dollar P&L is separated from opening/unrelated positions; absent fills cannot imply a measured return. Tuesday's orders and September 8–14 observations still require actual future broker receipts.
6. **Portfolio impact.** Read a complete Alpaca paper account and preview a hypothetical cash purchase against current direct holdings. Show position weights, cash, broker open buys, deduplicated local reservations, approved undispatched schedule buys, and active strategy budgets. Budgets are displayed separately because they can include invested capital. ETF look-through, correlations, future prices, taxes and funding approval are not inferred. The preview creates a saved advisory record only.

## Evidence and operational boundaries

- No new AI API key is required: briefs retain the configured Codex subscription adapter. Company metrics use the existing Finnhub connection; filings use SEC public endpoints.
- Sources and narrative are untrusted data. The brief model still has no tool or execution authority and retains citation/excerpt validation.
- Filing excerpts are bounded selections, not a claim that all guidance has been interpreted or that an 8-K is necessarily an earnings event. Source links allow full review.
- Research data is saved in the additive `ui_research_desk` table. Source bytes live under `.research-artifacts/company/objects`; development inputs and complete outputs live under `.research-artifacts/development/objects`.
- Local API downtime pauses monitor checks; startup resumes due checks. The visible worker timestamp and saved review timestamps are distinct.
- The two already approved paper orders and their schedule remain unchanged. The six workflows add no execution permission.

## First development observation

The fixed 2023 reconstruction produced approximately **26.91%** net simulated strategy return versus **55.71%** for the constrained fixed-basket control. Doubled costs produced **25.98%** versus **55.53%**. The strategy therefore did not beat its basket control in this experiment. These are retrospective exploratory results under the preserved assumptions, not a forecast or proof of profitable strategy research. The complete receipts retain drawdown, fills and entry-pause events.

## API reference

All routes are below `/api/discover/desk`:

- `GET /status`, `GET /records/{company|monitor|review|experiment|allocation}`
- `POST /company/{symbol}`, `POST /screen`
- `POST /monitors`, `POST /monitors/{id}/review`, `POST /monitors/{id}/toggle`
- `POST /experiment`, `GET /trial`, `POST /allocation`

Official source contracts: [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [SEC developer resources](https://www.sec.gov/about/developer-resources), [Finnhub SDK](https://github.com/Finnhub-Stock-API/finnhub-python).

## Verification — September 6, 2026

- Production web build passed; 101 selected backend tests and all 163 frontend tests passed.
- Browser step-through covered company refresh, financial screening with pass/unknown results, thesis save/review/pause, saved experiment tables, paper-trial evidence, and portfolio impact.
- The example PLTR monitor is saved and paused. Its baseline and review survive service restarts.
- Astra brief `brief_1134d8ead21c4181adad41b8b4033dc9` completed using `gpt-6-astra`, with 9,585 observed input tokens, 876 output tokens, and no citation-validation errors. It cited saved financial facts and a filing excerpt. These checks establish source references, not the correctness of every interpretation.
- An earlier request, `brief_723c71cba05b41d8883ac2a8dca109f5`, ended without a confirmed provider receipt and remains unknown. A separate explicit verification request succeeded; there was no automatic retry. Future child failures now retain sanitized diagnostics.
- Development result `desk_0713987a0ba5482a8baa9ffd42375bec` pins manifest `6d9a761d8a369325c3107e32d08db4f460e9eecfa324258c743222363bdfd524`.
- A $1,000 hypothetical PLTR allocation showed $89,884.46 cash after purchase and $89,484.46 after including the two already approved $200 NVDA schedule legs. The calculation created no broker order.
- The approved schedule retained content hash `729ec75513a03ff8d33800395f985a85f8cdf1cff0aa3336e5623553a4c23f35`; both exact orders remained approved with no submission receipt. All five trial sessions remained pending.
- API/web restarted successfully and the existing research, deployment and execution-scheduler workers reported heartbeats. The new research-desk worker also reported a fresh check without error.
