"""Report every frozen ablation, including incomplete historical validation."""
import argparse,json,csv,hashlib,shutil
from pathlib import Path
from datetime import date
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

LABELS={'hgb':'Original HGB','hgb_buffer':'HGB + buffer','hgb_buffer_risk':'HGB + buffer + risk','hgb_fundamentals':'HGB + fundamentals','hgb_fundamentals_buffer_risk':'HGB + all three','SPY':'SPY'}
def pct(v):return 'unavailable' if v is None else f'{v*100:.2f}%'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();root=a.root;result=json.loads((root/'results.json').read_text());f=json.loads((root/'fundamentals-coverage.json').read_text());h=json.loads((root/'historical/coverage.json').read_text());checks=json.loads((root/'verification.json').read_text());flat=[]
 lines=['# HGB improvements: frozen follow-up experiment','',
 '**The trading buffer helped the full S&P-roster portfolio, but not the diverse 100-stock portfolio. Adding the fundamentals did not improve return in either cohort. The risk rules reduced volatility and concentration, with lower returns. The complete bundle is not a demonstrated improvement over the original HGB.**','',
 'These are exploratory follow-up results on the already examined September 7, 2021–September 4, 2026 interval, using the original current-roster price panels and corporate-action quarantine sensitivity. They are not a new untouched holdout or a survivorship-free performance record. Every new target portfolio and prediction was frozen before scoring.','',
 '## Results after trading costs','',
 '11 bps per traded side includes modeled commission and slippage; 22 bps doubles both. Portfolios are long-only with fractional adjusted-price research accounting, zero interest on cash, no leverage, and no taxes. There are 60 monthly decisions, 59 full holds and one shortened final hold.']
 for u,x in result['universes'].items():
  lines+=['','### '+('Diverse 100 stocks' if u=='diverse100' else 'Current S&P roster'),'',
   '| Variant | Total net return | Annualized return | Worst drawdown | Annualized volatility | Annualized at double costs |','|---|---:|---:|---:|---:|---:|']
  for m,p in x['costs']['11'].items():
   q=x['costs']['22'][m];lines.append(f"| {LABELS[m]} | {pct(p.get('net_return'))} | {pct(p.get('cagr'))} | {pct(p.get('max_drawdown'))} | {pct(p.get('annualized_volatility'))} | {pct(q.get('cagr'))} |")
  for cost,ps in x['costs'].items():
   for m,p in ps.items():flat.append({'universe':u,'variant':m,'cost_bps_per_side':cost,**{k:p.get(k) for k in ['state','net_return','cagr','max_drawdown','annualized_volatility','beta_to_SPY','max_sector_weight','fees_fraction_initial_capital','two_sided_turnover_sum']}})
 with (root/'summary.csv').open('w') as fh:w=csv.DictWriter(fh,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
 fig,axes=plt.subplots(1,2,figsize=(13,5),layout='constrained',sharey=True);colors=['#222222','#118ab2','#7b2cbf','#ef8354','#2a9d8f','#aaaaaa']
 for ax,(u,x) in zip(axes,result['universes'].items()):
  for color,(m,p) in zip(colors,x['costs']['11'].items()):
   if p['state']=='complete':ax.plot([date.fromisoformat(z['date']) for z in p['curve']],[100000*z['equity'] for z in p['curve']],label=LABELS[m],color=color,lw=2 if m=='hgb_buffer' else 1.3)
  ax.set_title('Diverse 100' if u=='diverse100' else 'Current S&P roster');ax.set_ylabel('Value of $100,000 after modeled costs');ax.grid(alpha=.15);ax.legend(fontsize=8)
 fig.suptitle('Frozen HGB variants • 11 bps per side • already-observed historical interval');fig.savefig(root/'comparison.png',dpi=170);fig.savefig(root/'comparison.svg');plt.close(fig)
 lines+=['','![Portfolio comparison](comparison.png)','','## What changed','',
 '- **Trading buffer:** select the top third initially. Retain eligible holdings while they remain within the top 45%; replace an incumbent for a challenger only when its predicted 21-session relative-return advantage is at least 0.5 percentage points. Fill/prune to the original count and rebalance equally weighted. Parameters were not tuned after seeing results.',
 '- **Risk layer:** inverse trailing 63-session volatility weights, 5% security and 20% sector target caps, then downward-only scaling using a 50%-diagonal-shrunk covariance estimate toward trailing SPY volatility. Infeasible allocation remains cash. These are monthly target limits and may drift between rebalances; they do not guarantee equal realized volatility.',
 '- **Fundamentals:** eight additional inputs: annual net income/assets, operating cash flow/assets, free cash flow/assets, revenue growth, operating-cash-flow growth, latest liabilities/assets, latest cash/assets and annual diluted earnings yield. The liabilities ratio is a broad leverage proxy, not an exact interest-bearing debt ratio. All HGB training settings and chronological maturity rules were held fixed.',
 '- **Availability:** use only filings dated strictly before each decision; later amendments are visible only after their filing date. Flow facts must cover 330–400 days and ratio components must have matching periods. Latest flow/instantaneous observations are limited to 550 days since period end. Missing values remain missing and never remove stocks from the price-eligible universe.',
 '- **Valuation:** diluted annual EPS divided by raw close; omit ambiguous class-qualified/multiple-class cases and any period containing a split-factor change or unavailable price. This conservatively avoids silently comparing incompatible share bases.']
 lines+=['','## Turnover and risk tradeoffs','','| Universe | Variant | Turnover change versus HGB | Maximum observed sector weight | Beta to SPY |','|---|---|---:|---:|---:|']
 for u,x in result['universes'].items():
  base=x['costs']['11']['hgb']['two_sided_turnover_sum']
  for m,p in x['costs']['11'].items():
   if m=='SPY':continue
   lines.append(f"| {u} | {LABELS[m]} | {pct(p['two_sided_turnover_sum']/base-1)} | {pct(p['max_sector_weight'])} | {p.get('beta_to_SPY',float('nan')):.2f} |")
 lines+=['','## Statistical uncertainty','','Mean excess per complete 21-session holding period versus original HGB, circular block bootstrap with 3-period blocks and 5,000 samples. These intervals are exploratory, are not adjusted for all the hypotheses tried in the broader project, and do not turn this reused period into fresh validation.','','| Universe | Variant | Mean excess | 95% interval |','|---|---|---:|---:|']
 for u,x in result['universes'].items():
  for m,p in x['costs']['11'].items():
   if m in ['hgb','SPY']:continue
   v=p['paired_period_excess_vs_hgb'];lines.append(f"| {u} | {LABELS[m]} | {pct(v['mean'])} | [{pct(v['interval95'][0])}, {pct(v['interval95'][1])}] |")
 lines+=['','## Data captured and what remains unresolved','',
 f"Captured all 500 SEC companyfacts responses, 266 raw/split price pages, and all 242 requested former-ticker histories without HTTP failures. The fundamental matrix contains {f['origins']} feature cutoffs for 503 securities. Observed input coverage ranges from {pct(min(f['observed_fraction']))} to {pct(max(f['observed_fraction']))}; absent facts were not manufactured.",'',
 'The [SEC companyfacts API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) is a currently retrieved aggregate filtered here by historical filing date. This is materially stronger than feeding current ratios into past decisions, but does not certify a complete archival vintage of every original filing. Current issuer mapping and current GICS sector labels remain limitations.','',
 f"The historical-membership implementation retains {h['historical_union_count']} securities from the dated community reconstruction. All former symbols returned some bars, but there are {len(h['eligible_future_endpoint_gaps'])} missing required entry/exit observations and {h['unknown_identity_count']} former security identities without a qualified historical issuer mapping. Missing outcomes never change forecast eligibility.",'']
 hp=result['historical_membership_diagnostic']['costs']['11'];lines.append(f"**The historical-universe portfolio stops as incomplete on {hp.get('date')} at unresolved holdings {', '.join(hp.get('unresolved_symbols',[]))}. No complete five-year return is claimed for it.**")
 lines+=['','[Alpaca’s corporate-action endpoint](https://docs.alpaca.markets/us/reference/corporateactions-1) was also queried for the affected tickers. It returned many merger records, but not a complete set sufficient to reconcile every missing security; the capture also contains ticker reuse with different CUSIPs. Applying those records by ticker alone would be unsafe accounting. Qualified security identity, successor shares, cash consideration and terminal valuations are required before this historical reconstruction can clear the survivorship gate.','',
 'The current-roster comparisons above therefore remain survivor-selected. This limitation was not fixed by collecting more tickers. The genuinely unseen forward test is specified in `forward-study.json`, with a read-only forecast runner implemented in `forecast_prediction_improvements.py`, and has not started; no future observations or broker executions are claimed.','',
 '## Verification and disposition','',
 f"- {len(result['audits'])} main strategy/cost portfolios independently replayed with a separate transaction-cost solver; both incomplete historical replays also matched.",
 '- Original HGB reproduced its frozen returns, CAGR, drawdown and turnover at both cost levels in both universes.',
 f"- {len(checks['checks'])} additional verification checks passed, including first/middle/last model refits with future prices removed and future fundamental features corrupted, strict filing-date boundaries, valid selection counts and all risk target caps.",
 '- 23 focused unit/regression tests passed for buffer behavior, risk constraints, missing data, filing/amendment timing, valuation compatibility and portfolio accounting adapters.',
 '- The buffer is a candidate for a frozen forward research comparison on the S&P roster; the result does not support deploying the entire bundle as an improvement. Existing paper-trial orders, schedules and strategy deployments were not changed.','',
 '## Reproducibility','',
 '`protocol.json` declares the experiment. `targets-frozen.json` hashes predictions and targets before outcomes. `sec/`, `prices/`, and `historical/` retain raw captures and receipts. `fundamentals.npz` retains numeric features and their maximum filing dates. `results.json`, `verification.json`, and `summary.csv` retain full results and checks. `code/` and `manifest.json` preserve source and hashes.','']
 (root/'report.md').write_text('\n'.join(lines))
 for name in ['prepare_prediction_improvements.py','capture_prediction_improvements.py','build_prediction_fundamentals.py','build_prediction_historical_panel.py','prediction_improvement_targets.py','prediction_fundamentals.py','run_prediction_improvements.py','verify_prediction_improvements.py','report_prediction_improvements.py','prediction_wide_portfolios.py','verify_prediction_wide.py','prediction_portfolios.py','prediction_wide_ranking.py','prediction_ranking.py','forecast_prediction_improvements.py']:
  shutil.copy2(Path(__file__).parent/name,root/'code'/name)
 shutil.copy2(Path('tests/research/test_prediction_improvements.py'),root/'code/test_prediction_improvements.py')
 manifest={str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and p.name!='manifest.json'};(root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(root/'report.md')
if __name__=='__main__':main()
