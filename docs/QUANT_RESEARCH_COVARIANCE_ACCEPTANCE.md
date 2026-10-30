# Trend portfolio covariance acceptance

Verified 2026-09-04 Pacific. This closes the trend decision risk-estimate requirement in the [design](QUANT_RESEARCH_DESIGN.md); deployment, genuine-data research and the full release remain incomplete.

## Calculation and boundaries

New trend and fixed-basket target decisions persist a descriptive covariance risk estimate at their exact capped weights. The sample uses the frozen trend volatility window, aligned completed sessions and the same available split/dividend-adjusted total returns as the signal. Missing or late bars prevent both a target and a risk estimate. Future bars cannot alter past estimates. The sizing volatility floor is deliberately excluded from observed covariance.

For the sample covariance matrix `S` and capital weights `w`, annualized variance is `252 * w' S w`. The implementation computes the equivalent variance of aligned weighted returns and each asset's covariance with that portfolio, avoiding a quadratic matrix in every artifact. Annualized volatility contributions are `w_i * (252 S w)_i / volatility`; their sum equals portfolio volatility. Group shares sum asset variance contributions. Negative contributions and shares above 100% remain visible when another holding hedges risk. The relationship between exposure, covariance and risk attribution is discussed in [MSCI's portfolio risk attribution paper](https://www.msci.com/documents/10199/248121/Build_Risk_Parity_Portfolios_with_Correlation_Risk_Attribution_Nov_2011.pdf/36c8ed57-cfad-4d77-8d40-6cbcc107a778?version=1.0).

The report includes sample dates/count, input fingerprint, capital exposure, standalone volatilities, portfolio volatility, an explicitly hypothetical independence comparison, diversification ratio and per-asset/group contributions. Zero observed variance is valid; normalized contributions and diversification ratio are then undefined. Short samples and necessarily rank-deficient invested universes have explicit limitations. No matrix inversion, optimization, covariance shrinkage or weight changes were introduced.

This is proposed-weight price risk before share rounding, human approval or fills. It excludes changing cash yields, costs, liquidity and unobserved gap risks, and square-root annualization does not estimate serial dependence. It is neither a full portfolio volatility-targeting strategy nor a guarantee about future loss. Guidance and cash/reference paths without a trend estimate report absence explicitly. Older immutable artifacts are not rewritten.

## Verification

- Independent examples: equal 1% daily asset volatilities under perfect positive correlation give 1% portfolio volatility; opposite returns at equal weights give zero sample portfolio variance. A 60%/20% offsetting allocation retains 20% cash, produces 0.4% daily portfolio volatility and 150%/-50% variance contributions. An uncorrelated example matches the independence calculation. Constant returns, cash-only portfolios, missing/misaligned samples, invalid returns and leverage are covered.
- Trend tests preserve economic invariance through splits/dividends and confirm sample dates, capped weights, unavailable observations and future-data isolation. Focused kernel/replay suite: **24 passed**.
- Broader research/broker/provider/repository/room suite: **232 passed, 12 explicit native skips**, one expected test-model warning, 42.16 seconds. `/tmp/trademaster-covariance-regression.log`.
- Separate actual offline LEAN/reference suite: **21 passed**, 147.01 seconds, including all 12 cases skipped above. Exact shared target decisions, now including covariance estimates, matched native/local engines. Native fills/accounts, repeated execution, cancellation and worker recovery remained green. `/tmp/trademaster-covariance-native.log`.
- Frontend: **160 passed**, `/tmp/trademaster-covariance-webtests.log`; production build passes with four existing warnings, `/tmp/trademaster-covariance-build.log`. No new package dependency.

## Product flow

Research → Strategy research → saved fixture → inspect strategy run exposes a selector for 13 persisted decision estimates. Selecting January 3 versus March 27 changes the sample window and asset/group attribution from the saved artifact. The figure uses real stored equity data; the risk section describes proposed weights separately from realized volatility above it. The browser retained explicit fixture status and no promotion authority. No JavaScript exception or horizontal page overflow was observed.

Artifacts, isolated SQLite database and screenshots are in `/tmp/trademaster-covariance-ui/`. `seed.py` used the actual durable worker and all nine local scenario/control paths with a synthetic dataset. Experiment `exp_58bc938e6c834efb958b695317519288` links strategy `strategy_d6f0f587df774a568f03cbce3a950b34` and version `sv_409b0e3306404c5a8057bc6a6bc0104c`. After the final production rebuild/reload, selecting `decision-1` again showed January 3 and the correct saved contribution table, with no error or overflow; see `risk-final.png`. No remote provider, broker or model call was made. These synthetic numbers validate software only.

The acceptance browser and owned API/web processes were stopped after verification. No research containers remained running.
