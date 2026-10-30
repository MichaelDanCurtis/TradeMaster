# Forecast model challengers

Research reviewed September 7, 2026. These are candidates to test against the
same frozen historical cases, not models established to beat TimesFM-3 on equities.
The initial review was followed by completed local CPU benchmarks of Chronos-2,
Kronos Small, the larger Kronos Base, and Sundial. See
[executed comparison](FORECAST_CHALLENGER_BENCHMARK.md) for results and evidence.

| Priority | Model | Fit | Local support | Evidence boundary |
| --- | --- | --- | --- | --- |
| 1 | Amazon Chronos-2, 119.5M, Apache-2.0 | Univariate and multivariate targets, past-only covariates; closest match to current inputs | Official CPU inference; community MLX port needs independent parity tests | General benchmark comparisons include TimesFM-2.5, not TimesFM-3; equity advantage unproved |
| 2 | NeoQuasar Kronos-small, 24.7M plus tokenizer, MIT | Finance-specific OHLCV and timestamp input; requires additional preserved fields | Official CPU/MPS paths; no MLX port verified | Finance evaluation is relevant, but Small must not inherit claims from larger models or different markets |
| 3 | THU Sundial-base-128m, Apache-2.0 | Stock-only probabilistic forecast challenger | Official model card reports M1 Pro CPU/16 GB measurements | General forecasting evidence; sample count and random seeds must be frozen |

Chronos-2-Synth is an optional control trained solely on synthetic data. It can
help investigate historical pretraining overlap, but does not guarantee accuracy.

## Sources and exact model revisions

- [Chronos-2 model](https://huggingface.co/amazon/chronos-2), revision
  `29ec3766d36d6f73f0696f85560a422f50e8498c`.
- [Chronos-2 paper](https://arxiv.org/html/2510.15821v1).
- [Chronos pipeline](https://github.com/amazon-science/chronos-forecasting/blob/main/src/chronos/chronos2/pipeline.py).
- [Community Chronos-2 MLX implementation](https://github.com/tsfm-ai/chronos2-mlx),
  [mlx-chronos2 0.0.1](https://pypi.org/project/mlx-chronos2/0.0.1/).
  Maintainer parity/performance claims have not been reproduced here.
- [Kronos-small](https://huggingface.co/NeoQuasar/Kronos-small), revision
  `901c26c1332695a2a8f243eb2f37243a37bea320`;
  [tokenizer](https://huggingface.co/NeoQuasar/Kronos-Tokenizer-base), revision
  `0e0117387f39004a9016484a186a908917e22426`.
- [Kronos-base](https://huggingface.co/NeoQuasar/Kronos-base), revision
  `2b554741eca47781b64468546e77fef3e85130e6`, 102,311,008 parameters.
  The official 499.2M Large checkpoint remains unreleased as of this review.
- [Kronos paper](https://arxiv.org/html/2508.02739v1),
  [official model/device code](https://github.com/shiyu-coder/Kronos/blob/master/model/kronos.py).
- [Sundial model and Mac measurements](https://huggingface.co/thuml/sundial-base-128m),
  revision `3212e42564493f520593e5414af4367fc4b49226`.
- [Chronos-2-Synth](https://huggingface.co/autogluon/chronos-2-synth), revision
  `3607918a9fd027d5c465d8213e46b98e2c041cea`.

## Evaluation contract for the next challenger

Use the exact preserved windows in
`.research-artifacts/forecast/expanded-52-window-benchmark/intent.json`.
Retain flat and 256-session drift controls, every failed run, and the existing
price-scaled error calculation. Avoid choosing inputs, windows or model settings
based on the resulting test scores. Report known historical-data revisions,
pretraining overlap and sample concentration.

For Chronos, disable cross-learning and isolate different historical cutoffs.
Cross-learning/group attention can otherwise let later windows expose earlier
outcomes. The community MLX implementation documents automatic batch grouping;
verify its semantics and CPU parity before using it for this benchmark. Upstream
CPU is the first reference target. Quantized MLX would be a separate qualification.

Random-walk and drift baselines are already included; see
[Forecasting: Principles and Practice](https://otexts.com/fpp3/simple-methods.html).
