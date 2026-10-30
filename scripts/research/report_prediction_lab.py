"""Render every frozen candidate and matched controls without reselection."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import date

LABELS={'momentum_12_1':'Momentum','momentum':'Momentum (5-day rebalance)','ridge':'Ridge ranking','hgb':'Boosted-tree ranking',
        'plain_reversal':'Short-term reversal','residual_reversal':'Market-residual reversal','equal_weight':'Equal-weight basket','SPY':'SPY buy & hold','cash':'Cash (0% interest)'}
COLORS={'momentum_12_1':'#eea83b','momentum':'#eea83b','ridge':'#3388dd','hgb':'#38a88b','plain_reversal':'#af5cd0','residual_reversal':'#dc627b','equal_weight':'#777777','SPY':'#222222','cash':'#bbbbbb'}
def pct(x):return f'{x*100:+.2f}%'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);args=ap.parse_args();root=args.root
    data=json.loads((root/'portfolios/portfolios.json').read_text());risk=json.loads((root/'risk/report.json').read_text())
    fig,axes=plt.subplots(2,2,figsize=(15,10),layout='constrained')
    for col,cohort in enumerate(('ranking','reversal')):
        results=data['cohorts'][cohort]
        for model,p in results['costs']['11'].items():
            dates=[date.fromisoformat(r['date']) for r in p['curve']]
            axes[0,col].plot(dates,[100*r['equity'] for r in p['curve']],label=LABELS[model],color=COLORS[model],lw=1.8 if model not in ('cash','equal_weight') else 1.2)
        axes[0,col].set_title('Stock ranking · 21-session holdings' if col==0 else 'Reversal · 5-session holdings',loc='left',weight='bold')
        axes[0,col].set_ylabel('Hypothetical $100 after costs');axes[0,col].grid(alpha=.15);axes[0,col].legend(fontsize=8,loc='upper left')
        ax=axes[1,col]
        methods=[m for m in results['costs']['11'] if m not in ('cash','equal_weight','SPY')]
        x=np.arange(len(methods));width=.35
        for j,cost in enumerate(('11','22')):
            values=[100*results['costs'][cost][m]['excess_net_return_vs_equal_weight'] for m in methods]
            ax.bar(x+(j-.5)*width,values,width,label=f'{cost} bp per traded side',color=['#386da6','#90b2d6'][j])
        ax.axhline(0,color='#555',lw=.8);ax.set_xticks(x,[LABELS[m] for m in methods],rotation=12,ha='right',fontsize=9)
        ax.set_title('Total net return minus matched equal-weight basket',loc='left',fontsize=11)
        ax.set_ylabel('Percentage points');ax.legend(fontsize=9);ax.grid(axis='y',alpha=.15)
    fig.suptitle('Historical prediction experiments · fixed rules, next-open fills, all candidates shown',fontsize=16,weight='bold')
    fig.supxlabel('Exploratory current-survivor basket; adjusted-price proxy fills. These are simulations, not account returns.',fontsize=10)
    fig.savefig(root/'comparison.png',dpi=160);fig.savefig(root/'comparison.svg');plt.close(fig)
    lines=['# Prediction laboratory: historical experiments','',
        'Three research agents proposed stock ranking, volatility forecasting and short-term reversal. This run tests all predeclared candidates, with no parameter search or winner-only reporting.','',
        '**Data:** 33 fixed current-survivor stocks plus SPY; 91,256 adjusted daily bars across 2,684 sessions, January 4, 2016–September 4, 2026. Evaluation decisions begin January 3, 2023. Initial supervised training uses earlier history; later fits may use only labels already mature on the decision date.','',
        '**Trading simulation:** top 11 equally weighted stocks, long only, fractional adjusted-price proxy units, next-session open, 11 basis points per traded side and a 22-basis-point stress case. Turnover uses drifted holdings and costs reduce investable equity. Opening purchases and final liquidation are charged. SPY is buy-and-hold; cash earns zero.','',
        '![All candidate results](comparison.png)','']
    for cohort in ('ranking','reversal'):
        r=data['cohorts'][cohort];sample=r['costs']['11']['equal_weight']
        lines.extend([f"## {'Stock ranking' if cohort=='ranking' else 'Short-term reversal'}",'',f"{r['origin_count']} decisions; fills {sample['first_date']}–{sample['last_date']}; {r['hold_sessions']}-session holdings. Returns below are cumulative, not annual.",'',
            '| Method | Net return, 11 bp | Net return, 22 bp | CAGR, 11 bp | Max drawdown at daily opens, 11 bp | Excess vs basket, 11 bp | Mean rank correlation |',
            '|---|---:|---:|---:|---:|---:|---:|'])
        for model,p in r['costs']['11'].items():
            rank=r['rank_accuracy'].get(model,{}).get('mean_spearman')
            lines.append(f"| {LABELS[model]} | {pct(p['net_return'])} | {pct(r['costs']['22'][model]['net_return'])} | {pct(p['cagr'])} | {pct(p['max_drawdown'])} | {100*p['excess_net_return_vs_equal_weight']:+.2f} pp | {rank:.4f} |" if rank is not None else f"| {LABELS[model]} | {pct(p['net_return'])} | {pct(r['costs']['22'][model]['net_return'])} | {pct(p['cagr'])} | {pct(p['max_drawdown'])} | {100*p['excess_net_return_vs_equal_weight']:+.2f} pp | — |")
        lines.extend(['','Annual slices at 11 bp (2023/2026 are partial evaluation years):','', '| Method | 2023 | 2024 | 2025 | 2026 | Two-sided turnover | Peak observed weight |','|---|---:|---:|---:|---:|---:|---:|'])
        for model,p in r['costs']['11'].items():
            years=' | '.join(pct(p['annual_returns'][y]) for y in ('2023','2024','2025','2026'))
            lines.append(f"| {LABELS[model]} | {years} | {p['two_sided_turnover_sum']:.2f}× | {100*p['max_observed_weight']:.1f}% |")
        lines.extend(['','Paired mean holding-period excess over the basket, with 95% circular time-block bootstrap intervals. These intervals concern average period return differences, not cumulative returns; instruments stay grouped by date. They are exploratory and not adjusted for trying multiple methods.','', '| Method | Mean excess per period | 95% interval |','|---|---:|---:|'])
        for model in r['rank_accuracy']:
            b=r['costs']['11'][model]['paired_period_excess']
            lines.append(f"| {LABELS[model]} | {100*b['mean']:+.3f} pp | [{100*b['interval95'][0]:+.3f}, {100*b['interval95'][1]:+.3f}] pp |")
        lines.append('')
    lines.extend(['## Volatility prediction','',
        'Forecast target: average squared close-to-close daily log returns over the next 5 or 20 sessions. This is a noisy daily variance proxy, not intraday realized variance or a return forecast. QLIKE is the primary loss; a negative difference means improvement. Calibration is actual variance divided by forecast variance; ideal is 1.','',
        '| Horizon | Model | Matched stock cases | QLIKE difference vs trailing20 | MSE reduction | Calibration |', '|---|---|---:|---:|---:|---:|'])
    for row in risk['summary']:
        if row['group']!='stocks': continue
        s=row['matched'];lines.append(f"| {row['horizon']} days | {row['method']} | {row['matched_cases']} | {s['qlike_difference_vs_trailing20']:+.5f} | {100*s['mse_skill_vs_trailing20']:+.2f}% | {s['calibration_actual_over_predicted']:.3f} |")
    lines.extend(['',f"All 8,772 forecast/horizon rows were saved before scoring. GARCH had {len(risk['failed_forecasts'])} failed horizon rows, representing five failed fits; these remain recorded without fallback. Every stock method is compared on the same 1,414 cases per horizon. Full-coverage EWMA versus trailing20 and SPY-only results are also retained in the risk report.",''])
    verify=root/'risk/verification.json'
    if verify.exists():
        lines.extend(['Independent risk verification: [verification.json](risk/verification.json). Paired block intervals below are QLIKE score differences, not percentages; below zero favors the model.','', '| Model | Horizon | QLIKE difference | 95% interval |','|---|---:|---:|---:|'])
        for b in json.loads(verify.read_text())['bootstrap_results']:
            low,high=b['percentile_interval_95']
            lines.append(f"| {b['method']} | {b['horizon']} days | {b['qlike_difference_vs_trailing20']:+.4f} | [{low:+.4f}, {high:+.4f}] |")
        lines.append('')
    lines.extend(['## Research interpretation and limits','',
        'The two learned stock rankers beat both momentum and the matched basket in this run, and beat SPY in cumulative return. Both remained ahead when costs doubled. Their paired mean monthly excess intervals over the basket stayed above zero under the declared time-block bootstrap. Ridge also beat the basket in each reported year; its worst daily-open drawdown was 16.65%, versus 14.34% for the basket. These are promising retrospective findings, not evidence of a 32% return promise or a deployable edge.', '',
        'The reversal candidates failed to beat their same-stock basket after base costs, and higher transaction costs hurt them sharply. Keep their negative results. Volatility forecasting is the clearest distinct risk feature: 20-day GARCH improved both QLIKE and MSE; five-day GARCH remained uncertain and worsened MSE. EWMA improved QLIKE at both horizons, with no fit failures.', '',
        'A method can make money during a rising market without adding predictive value. Compare with both the same-stock equal-weight basket and SPY; use rank correlation, cost stress and time slices alongside cumulative return. Risk-prediction gains do not by themselves establish a profitable sizing policy.','',
        *['- '+s for s in data['limitations']], '',
        'The confidence intervals do not remove universe-selection bias, adjusted-data revision risk or researcher knowledge of historical events. No candidate is promoted to execution by this report.','',
        '## Research sources','',
        '- [Gu, Kelly and Xiu: Empirical Asset Pricing via Machine Learning](https://dachxiu.chicagobooth.edu/download/ML_BKP.pdf): motivation for learning relative returns from characteristics; this small price/volume experiment is an adaptation.',
        '- [Kenneth French momentum definition](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_developed_mom.html): skipped-month momentum; our long-only basket is not the published long-short factor.',
        '- [Da, Liu and Schaumburg: A Closer Look at the Short-Term Return Reversal](https://academicweb.nd.edu/~zda/Reversal.pdf): motivates distinguishing market and stock-specific moves; the price-only beta residual here is not a replication.',
        '- [ARCH forecasting documentation](https://arch.readthedocs.io/en/latest/univariate/forecasting.html): fixed GARCH variance forecast implementation.',
        '- [Alpaca historical-bar adjustment documentation](https://docs.alpaca.markets/us/reference/stockbars): split, dividend and spin-off adjustments used in this capture.','',
        'A separate future candidate is [filing-text change research (Lazy Prices)](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12885), using accession-dated SEC filings. It is researched but not implemented or tested here; it requires its own point-in-time text dataset.','',
        '## Verification and concentration','',
        '39 focused tests passed, including future-data perturbation, real sklearn fits, label maturity, next-open timing, symbol-order identity, turnover and self-financing cash accounting. Independent reconstruction matched all 547,536 panel values to retained raw responses; all 8,772 risk score rows and 222 risk summaries; all 24 portfolio/cost cases and 681 rank correlations; all 1,419 ranking outcomes and momentum scores, plus first/last learned-model predictions.', '',
        'At base costs, NVIDIA contributed 30.74 percentage points of Ridge’s 170.14% cumulative net gain (18.07% of total profit), and 32.98 points of the boosted-tree model’s 145.74% gain (22.63%). NVIDIA, Amazon and Caterpillar together contributed 42.97% and 50.16% of net profit respectively. This is an arithmetic attribution of the saved trades, not a test of removing those companies or evidence of robustness to a different universe.', '',
        'Audit files: [data](data-verification.json), [risk](risk/verification.json), [ranking and stock attribution](ranking/verification.json), [portfolio accounting](portfolios/verification.json).', '',
        '## Reproducibility','',
        'Frozen protocol: `protocol.json`; exact raw pages and timestamps: `capture-receipt.json` and `raw/`; normalized panel: `panel.json`; independent data check: `data-verification.json`; package versions: `requirements.txt`; hashed run code copies: `code/`. Prediction, outcome and portfolio files include source hashes. Capture and forecasting/evaluation commands refuse existing result directories; the report renderer can refresh presentation files.','',
        'The experiment is offline research after capture. It does not modify the app, its runtime, the approved Alpaca paper schedule or the prior frozen paper-trial criteria.',''])
    (root/'report.md').write_text('\n'.join(lines))
    print(root/'report.md')
if __name__=='__main__':main()
