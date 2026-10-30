# Local research runner acceptance

Verified 2026-09-04. This is software evidence for the local trend research path, not completion of the full implementation plan or investment validation.

## Checks run

```sh
.venv/bin/python -m pytest tests/research tests/ui/test_repository.py tests/ui/test_room_policy.py -q
```

Result: **84 passed**. Includes immutable versions/families, concurrent idempotency, lease recovery, publication/receipt timing, imports and artifact integrity, next-session fills, frozen quantities under opening gaps, holidays, fees/slippage, splits and fractional cash, dividend receivables/payment dates, zero-recovery delisting, missing valuations, no-trade/undefined metrics, drawdown pause, subprocess cancellation/runtime termination, unavailable engines, per-version report validation and preserved legacy records.

From `apps/web`:

```sh
npm run build
```

Result: production build, lint error gate and TypeScript check pass. Four existing lint warnings and six source-assertion failures in the broader frontend test suite are listed in [the implementation status](QUANT_RESEARCH_IMPLEMENTATION_STATUS.md). Full frontend release acceptance remains open.

## Browser walkthrough

Used the production app at `http://127.0.0.1:3000` and an API with a separate database at `/tmp/trademaster-research-ui/ui.db`. Model runs were disabled and the test account had no configured provider. Browser automation used the `trademaster-research` session.

1. Confirmed the existing four-room shell and symbol-research empty state render without an error overlay.
2. Opened Strategy research and created an actual persisted hypothesis through its form.
3. Selected the explicitly synthetic universe, froze its trend rules and the example dated test plan.
4. Loaded the synthetic dataset, queued an experiment and observed a truthful offline-worker/queued state.
5. Ran the worker with `--once`; the UI automatically loaded the completed report with nine rows (strategy, fixed basket and cash under each of three cost scenarios).
6. Inspected the strategy equity curve, fees, unfilled orders, missing inputs, risk-limit sessions and uncertainty. The strategy underperformed the fixture basket; the unfavorable comparison was preserved.
7. Reloaded the page and reselected the strategy. The report and all nine rows persisted. The existing shell returns to Portfolio on reload; saved research records are retained.
8. Revised the draft through its form. Database verification confirmed revision 2 while the original frozen version's hypothesis remained unchanged.
9. Uploaded an invalid JSON dataset and observed a validation error, with no successful import.

Controls were exercised with keyboard focus and Enter as well as navigation clicks. No JavaScript exception or framework overlay was detected. The existing watchlist logged an expected unavailable-quote warning because no provider was configured. Browser, API and web test servers were stopped afterward.

Screenshots remain at `/tmp/trademaster-research-ui/initial.png`, `/tmp/trademaster-research-ui/evidence.png` and `/tmp/trademaster-research-ui/equity.png`. Experiment ID: `exp_4c1fefb6a486451abaf032f56b64d028`. Its immutable report digest is `ebb471c77214e57ab0614bbe94842611a10437c9ba552b2b8cbad8574a1624c4`.

## Declared engine limits

The local engine supports USD, long-only, whole-share trend research. Strategy code sees point-in-time observations. The engine's separate execution model uses the later session's open and adverse slippage, rejects whole orders that violate exact cash/position/group/turnover constraints, and assumes one execution window. It does not model auction priority or guarantee those fills in a broker account. Between-window price drift can move existing holdings outside caps; the ledger reports this rather than rewriting history.

Dividends remain receivables until an explicit payment date. Fractional split compensation uses the opening price as a disclosed simulation assumption. Cash yield uses the declared simple ACT/365 assumption; taxes, settlement buying-power restrictions, hardware and operator expenses are excluded. Operating charges are recorded separately from trading P&L.

The code/runtime build digest includes research source, Python/runtime platform, Pydantic and decimal-library versions. Dataset and output artifacts have independent SHA-256 integrity checks. Local replay is never described as LEAN or broker evidence. The LEAN spike is recorded separately; a full LEAN adapter and shared-function parity are still outstanding.

Report uncertainty uses deterministic resampling of five-session blocks, sufficient-block checks and the frozen family trial ceiling. The interval is approximate and does not cover dependence beyond a block or structural breaks. It must not be treated as proof of a persistent edge. Genuine provider data, calibrated thresholds, the three-arm guidance/Astra comparison and the human-reviewed paper path remain future acceptance work under the active plan.
