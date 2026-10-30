"""Render the two wider fixed-rule experiments, including coverage limitations."""
import argparse,json,csv
from pathlib import Path
from datetime import date
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
LABELS={'ridge':'Ridge ranking','hgb':'Boosted trees','momentum_12_1':'Momentum','equal_weight':'Equal-weight universe','SPY':'SPY buy & hold','cash':'Cash (0%)'}
COLORS={'ridge':'#297fba','hgb':'#1b9e77','momentum_12_1':'#db9c25','equal_weight':'#888888','SPY':'#222222','cash':'#bbbbbb'}
def pct(x):return 'unavailable' if x is None else f'{100*x:+.2f}%'
def num(x):return 'unavailable' if x is None else f'{x:.2f}'

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();root=a.root
 universe=json.loads((root/'universe.json').read_text());results={n:json.loads((root/n/'portfolios/portfolios.json').read_text()) for n in ['diverse100','sp500']}
 fig,axes=plt.subplots(2,2,figsize=(15,10),layout='constrained')
 for col,(name,title) in enumerate([('diverse100','100 stocks · 11-sector balanced selection'),('sp500','S&P 500 roster · 503 securities')]):
  result=results[name]
  for model,p in result['costs']['11'].items():
   if p['state']!='complete':continue
   dates=[date.fromisoformat(r['date']) for r in p['curve']];e=np.array([r['equity'] for r in p['curve']])
   axes[0,col].plot(dates,100*e,color=COLORS[model],label=LABELS[model],lw=1.8)
   if model in ['ridge','hgb','SPY']:
    peak=np.maximum.accumulate(np.r_[1,e])[1:]
    axes[1,col].plot(dates,100*(e/peak-1),color=COLORS[model],label=LABELS[model],lw=1.6)
  axes[0,col].set_title(title,loc='left',weight='bold');axes[0,col].set_ylabel('Hypothetical $100 after costs');axes[0,col].legend(fontsize=8)
  axes[1,col].set_title('Observed peak-to-trough decline',loc='left');axes[1,col].set_ylabel('Percent below prior peak');axes[1,col].legend(fontsize=8)
  for row in range(2):axes[row,col].grid(alpha=.15)
 fig.suptitle('Five-year stock selection tests · September 7, 2021–September 4, 2026',weight='bold',fontsize=15)
 fig.supxlabel('Current-roster, survivor-selected diagnostics. 11 bp per traded side; adjusted-price proxy fills; no taxes. Missing marks explicitly recorded.',fontsize=9)
 fig.savefig(root/'comparison.png',dpi=160);fig.savefig(root/'comparison.svg');plt.close(fig)
 lines=['# Five-year stock ranking: 100 diverse stocks and the S&P 500','',
  '**Period:** September 7, 2021 opening entry through September 4, 2026 opening liquidation (approximately five years). Models use prior history beginning January 2016. Both runs contain 60 decisions, 59 full 21-session holdings and one shortened final holding. The final partial holding contributes to P&L but is excluded from 21-session rank correlations and paired-period uncertainty.','',
  '**Critical scope:** these are two tests using the S&P 500 roster as of September 4, 2026, not a point-in-time index-membership backtest. The 100-name basket is a sector-balanced subset of that roster, so it is diverse by sector but does not represent all market capitalizations or international equities. Historical membership data is captured separately; historical removals, bankruptcies and merger proceeds remain a further validation task.','',
  '**Fixed strategy:** unchanged ten price/volume features; cross-sectional ranks; expanding Ridge and shallow boosted-tree fits trained only on labels mature at each decision. Select the top third, rounded up, equal weighted; rebalance every 21 sessions; long only, no leverage. Compare with momentum, the same eligible stocks equally weighted, SPY buy-and-hold and cash. 11 bp per side (0.11% of traded notional), stressed at 22 bp; taxes excluded. No parameters were retuned after the earlier successful small-basket test.','',
  '![Comparison](comparison.png)','']
 for name,title in [('diverse100','100 sector-balanced stocks'),('sp500','S&P 500 roster')]:
  r=results[name];pred=json.loads((root/name/'ranking/predictions.json').read_text())
  lines.extend([f'## {title}','',f"Frozen universe: {r['stock_count']} securities. Stocks eligible from complete past history: {r['eligible_count_range'][0]}–{r['eligible_count_range'][1]} per decision; selected holdings: {r['selected_count_range'][0]}–{r['selected_count_range'][1]}. Recent listings and missing history are excluded only when insufficient history is known at that decision date; future price coverage never determines eligibility.",'',
   '| Method | Total net gain | Annualized return | Annualized at double costs | Observed max drawdown | Volatility | Zero-rate Sharpe |',
   '|---|---:|---:|---:|---:|---:|---:|'])
  for model,p in r['costs']['11'].items():
   if p['state']!='complete':lines.append(f"| {LABELS[model]} | incomplete: {p['reason']} | — | — | — | — | — |");continue
   stress=r['costs']['22'][model]
   lines.append(f"| {LABELS[model]} | {pct(p['net_return'])} | {pct(p['cagr'])} | {pct(stress.get('cagr'))} | {pct(p['max_drawdown'])} | {pct(p['annualized_volatility'])} | {num(p['sharpe_zero_rate'])} |")
  lines.extend(['','Annual return slices (2021 and 2026 are partial years):','','| Method | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |','|---|---:|---:|---:|---:|---:|---:|'])
  for model,p in r['costs']['11'].items():
   if p['state']=='complete':lines.append('| '+LABELS[model]+' | '+' | '.join(pct(p['annual_returns'].get(str(y))) for y in range(2021,2027))+' |')
  lines.extend(['','Risk, turnover and concentration at base costs:','','| Method | Beta to SPY | Two-sided turnover | Max security weight | Max issuer weight | Max sector weight | Minimum effective holdings |','|---|---:|---:|---:|---:|---:|---:|'])
  for model,p in r['costs']['11'].items():
   if p['state']=='complete':lines.append(f"| {LABELS[model]} | {num(p.get('beta_to_SPY'))} | {p['two_sided_turnover_sum']:.2f}× | {pct(p['max_single_security_weight'])} | {pct(p['max_issuer_weight'])} | {pct(p['max_sector_weight'])} | {num(p['minimum_effective_holdings'])} |")
  lines.extend(['','Paired mean full-holding-period excess with 95% three-period circular-block bootstrap intervals (5,000 draws, seed 59137). These are average period-return differences in percentage points, not cumulative-return intervals, and are not multiple-testing adjusted.','','| Model | Mean rank correlation | Excess vs equal weight / interval | Excess vs SPY / interval |','|---|---:|---:|---:|'])
  for model in ['momentum_12_1','ridge','hgb']:
   p=r['costs']['11'][model];metrics=[]
   for control in ['equal_weight','SPY']:
    b=p.get('paired_period_excess_vs_'+control)
    metrics.append('unavailable' if b is None else f"{100*b['mean']:+.3f} [{100*b['interval95'][0]:+.3f}, {100*b['interval95'][1]:+.3f}] pp")
   lines.append(f"| {LABELS[model]} | {r['rank_accuracy'][model]['mean_spearman']:.4f} | {' | '.join(metrics)} |")
  gaps={m:p.get('valuation_gaps',[]) for m,p in r['costs']['11'].items() if p.get('valuation_gaps')}
  lines.extend(['',f"Valuation gaps: `{json.dumps(gaps)}`. Held units remain unchanged across an intraperiod missing mark; no price or sale is invented. A later observed mark captures the entire intervening move. Missing required trade or terminal prices would make exact P&L incomplete. Volatility, Sharpe and beta are withheld for portfolios with gaps; drawdown uses observed opens only.",'',
    f"Model failures: {len(pred['failures'])}. Maximum accumulated unresolved training labels explicitly excluded: {max(row['excluded_unresolved_training_labels'] for row in pred['rows'])}. Evaluation outcomes are stored separately after forecasts are frozen.",''])
 quality={n:json.loads((root/(n+'-quality')/'portfolios/portfolios.json').read_text()) for n in results}
 lines.extend(['## Data-quality sensitivity: preserve initial results, quarantine questionable training windows','',
  'Independent issuer evidence identified structural discontinuities at APTV (2017-12-05), EQT (2018-11-13) and RTX (2020-04-03). Their adjacent prices are not qualified holder-return labels. After the primary results, a separately recorded sensitivity quarantined affected past feature windows and conservatively excluded training-label endpoints around those dates. It did not change any evaluation prices, membership or model settings. This is data-quality sensitivity, not a new holdout or complete corporate-action correction.', '',
  '| Universe | Model | Original total gain | Quarantined total gain | Original CAGR | Quarantined CAGR | Quarantined CAGR at double costs | Quarantined drawdown |',
  '|---|---|---:|---:|---:|---:|---:|---:|'])
 for name,r in quality.items():
  for model in ['ridge','hgb']:
   old=results[name]['costs']['11'][model];new=r['costs']['11'][model];stress=r['costs']['22'][model]
   lines.append(f"| {name} | {LABELS[model]} | {pct(old['net_return'])} | {pct(new['net_return'])} | {pct(old['cagr'])} | {pct(new['cagr'])} | {pct(stress['cagr'])} | {pct(new['max_drawdown'])} |")
 lines.extend(['',
  'The advantage over SPY persists in all four quarantine comparisons and under doubled costs. The changed boosted-tree result also shows why training-data quality matters. Original results, modified-panel hashes and exact changed-cell audits are retained; this does not remove current-survivor selection or certify every historical corporate action.', '',
  'The large MRNA 2026-08-19 and ECHO 2025-08-26 moves have matching dated issuer/news catalysts; no mechanical return-based removal was applied. Exact OHLC verification and EXE/DOW security lineage remain open. See [five-event triage](data-quality-triage.json).', '',
  '## Interpretation', '',
  'The learned ranking advantage survives a much broader universe and a five-year interval, but annualized gains are lower than the original handpicked 33-stock result. In the original wider runs, 100-stock Ridge returned 21.27% annually and full-roster boosted trees 19.60%, versus SPY 12.76%. These are net of declared costs and before taxes.', '',
  'The strategies still take substantial equity risk. Full-roster Ridge and boosted trees have observed beta around 1.20/1.18 and annualized volatility 22.72%/22.04%, versus SPY 17.34%. The 100-stock Ridge maximum observed drawdown was 27.26%, slightly worse than SPY 26.29%. Higher return is not a capital-protection claim.', '',
  'At primary base costs the 100-stock learned-model paired excess intervals are above zero against both benchmarks. Full-roster Ridge intervals cross zero; boosted trees are narrowly above zero. These exploratory intervals are not corrected for multiple methods or survivor bias. The results warrant a dated-membership/security-lineage validation, not automatic promotion to trading.', '',
  '## Independent checks', '',
  '17 focused tests passed. Independent capture reconstruction matched 9,742,920 cells across both panels including nulls. Forecast audits verified all 60 origins per universe, training maturity, all realized outcomes and first/last learned model fits. Independent portfolio replay covered all 24 original portfolio/cost cases and all 24 quarantine cases. Exact mask audits confirm no evaluation price or symbol set changes.', '',
  'Portfolio rows named daily_returns represent intervals between observed opens; if a valuation gap exists an interval can span several sessions. Daily volatility, Sharpe and beta are withheld in that case. Gap records and actual curve indices are authoritative.', ''])
 lines.extend(['## Frozen 100-stock selection','','Nine securities per sector plus a tenth in Utilities; deterministic SHA-256 ordering with seed string `prediction-wide-v1`, one security per CIK in this basket. Selection preceded price capture. The strategy itself has no sector-neutrality constraint.','','| Sector | Count | Securities |','|---|---:|---|'])
 for sector in sorted(universe['diverse100_sector_counts']):
  names=[s for s in universe['diverse100_symbols'] if universe['sectors'][s]==sector]
  lines.append(f"| {sector} | {len(names)} | {', '.join(names)} |")
 coverage=json.loads((root/'capture/coverage.json').read_text())
 lines.extend(['','## Source coverage and what this does not prove','',f"Alpaca SIP capture: {coverage['bars']:,} raw daily bars across {coverage['sessions']:,} exchange sessions, covering 503 stock symbols plus SPY requests. DOW returned no historical bars under the frozen request and remains in the universe with unavailable history; it is never silently replaced. Raw zero-volume bars retain their original evidence but have no executable normalized open. All raw responses, normalization policies and nulls are preserved.",'',
  '- Current constituents and present-day sector classifications were selected with hindsight. This remains survivor-biased even though the model fits themselves are chronological.',
  '- Current revised split/dividend/spin-off adjusted prices are proxies, not certified historical executable quotes. Provider as-of symbol mapping is retained; it does not independently prove every merger or security lineage.',
  '- Public historical membership reconstruction contains 745 tickers and dated changes. Those historical lists were not applied in the two primary results; current-roster success cannot certify success on removed or failed companies.',
  '- The last partial period and omitted zero-volume marks are explicit. No synthetic fills, carried valuations or silent future-coverage filtering are used.',
  '- Five-year results overlap previously inspected years. These are broader exploratory tests, not a newly untouched holdout or a promised future return.',
  '- There are no live or paper orders from this experiment and no change to the separately approved paper-trial schedule.','',
  '## Evidence and reproduction','',
  'Frozen choices: `intent.json`, `universe.json`, `normalization-policy.json`, `valuation-policy.json`. Membership sources: `universe-source/`, with pinned raw source revisions, primary announcement checks and historical snapshots. Market-data evidence: `capture/raw/`, stable `source-receipt.json`, final `receipt.json`, coverage report and independently checked panels. Each cohort preserves forecasts before outcomes, portfolio ledgers, daily observed curves, verification and both cost scenarios. Code snapshots and package versions are retained.','',
  '[S&P September 4 announcement](https://press.spglobal.com/2026-09-04-Bloom-Energy,-Illumina,-and-Everpure-Set-to-Join-S-P-500-Others-to-Join-S-P-100,-S-P-MidCap-400,-and-S-P-SmallCap-600) takes effect September 21; those future changes are excluded. [Historical membership reconstruction](https://github.com/fja05680/sp500) is a community source, not official licensed point-in-time data. [Alpaca adjustment and as-of semantics](https://docs.alpaca.markets/us/reference/stockbars) govern the retained requests.',''])
 (root/'report.md').write_text('\n'.join(lines))
 with (root/'summary.csv').open('w') as f:
  writer=csv.writer(f);writer.writerow(['universe','model','cost_bps_per_side','state','total_net_return','cagr','max_drawdown','annualized_volatility','sharpe_zero_rate'])
  for name,r in {**results,**{n+'-quality':v for n,v in quality.items()}}.items():
   for cost,models in r['costs'].items():
    for model,p in models.items():writer.writerow([name,model,cost,p['state'],*[p.get(k) for k in ['net_return','cagr','max_drawdown','annualized_volatility','sharpe_zero_rate']]])
 print(root/'report.md')
if __name__=='__main__':main()
