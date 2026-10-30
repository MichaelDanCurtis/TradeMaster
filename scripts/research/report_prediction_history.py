"""Report all additional-history tests, including incomplete and negative results."""
import argparse,csv,hashlib,json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime


def main(r):
 read=lambda p:json.loads(p.read_text());x=read(r/'event-results.json');v=read(r/'verification.json')
 identity=read(r/'identity-sensitivity/results.json')
 for u in ['diverse100','sp500']:x[u+'-early']['costs']=identity[u]
 pct=lambda z:'Unavailable' if z is None else f'{100*z:.2f}%'
 lines=['# Additional historical validation', '',
 '**The buffer improved the model in the earlier historical-membership test, but both strategies underperformed SPY and experienced a larger observed drawdown. This supports investigating the buffer as an implementation improvement, not claiming a proven market-beating strategy.**','',
 'The additional interval is March 4, 2019–September 3, 2021. There are 31 frozen decisions (30 full 21-session holds and one final partial hold) per universe, with signals beginning March 1. Models use only matured training labels and past features; all later prices were physically removed before this experiment. Rules were fixed before its forecasts. This is still a follow-up chosen after earlier research, not an untouched clean-room test.','',
 '## After-cost returns','',
 'Annualized returns at 11 basis points per traded side. Current-roster rows below use the separately recorded EXE inception correction; historical-membership results are unchanged. Cash earns no interest; no leverage or taxes. Fractional shares and adjusted prices are research conventions.','',
 '| Universe | Original HGB | HGB + buffer | SPY | State |','|---|---:|---:|---:|---|']
 for key,label in [('diverse100-early','Current-roster diverse 100'),('sp500-early','Current S&P roster'),('historical-early','Dated historical S&P membership')]:
  m=x[key]['costs']['11'];lines.append('| '+label+' | '+' | '.join(pct(m[k].get('cagr')) for k in ['hgb','hgb_buffer','SPY'])+' | '+('Full interval endpoints resolved*' if m['hgb']['state']=='complete' else 'Incomplete: EXE/old Chesapeake')+' |')
 lines+=['','*Endpoints reconcile, but the historical-membership and full current-roster portfolios each lack one daily open mark for BIIB on November 6, 2020. Return accounting completes; full daily volatility and Sharpe remain unavailable. Membership/security identity completeness is not certified. The 100-stock test still uses a survivor-selected starting roster.','',
 '## Risk and turnover','',
 '| Universe | Variant | Worst observed drawdown | Annualized volatility | Turnover change versus HGB | CAGR at double costs |','|---|---|---:|---:|---:|---:|']
 records=[]
 for key,label in [('diverse100-early','Diverse 100'),('sp500-early','Current S&P'),('historical-early','Historical S&P')]:
  baseline=x[key]['costs']['11']['hgb']['two_sided_turnover_sum']
  for name,z in x[key]['costs']['11'].items():
   change=z['two_sided_turnover_sum']/baseline-1
   lines.append(f'| {label} | {name} | {pct(z["max_drawdown"])} | {pct(z["annualized_volatility"])} | {pct(change) if name!="SPY" else "Buy and hold"} | {pct(x[key]["costs"]["22"][name]["cagr"])} |')
   records.append({'universe':key,'variant':name,'cagr':z['cagr'],'net_return':z['net_return'],'drawdown':z['max_drawdown'],'annualized_volatility':z['annualized_volatility'],'turnover_change_vs_hgb':change,'cagr_double_costs':x[key]['costs']['22'][name]['cagr']})
 lines+=['','For historical membership, the buffer adds about **0.81 percentage points** of annualized return and reduces turnover by about **18%**, while the observed drawdown is almost unchanged. It still trails SPY by about **1.98 percentage points annually**. Its observed drawdown is about 39.42%, versus SPY\'s 32.05%. For the current-roster 100, higher returns also come with higher volatility and a deeper drawdown than SPY; return alone is not a risk-matched victory.','',
 '## Security-inception correction and sensitivity','', 'The initial current-roster run treated pre-bankruptcy Chesapeake history as if it belonged to current EXE shares. The old equity was cancelled on February 9, 2021 and new shares began trading February 10. A separate, prespecified data-correction run masks EXE prices before that new-share start, preserving all other observations and model settings. It refits both models and freezes their new forecasts before scoring. [Issuer announcement](https://investors.expandenergy.com/news-releases/news-release-details/chesapeake-energy-corporation-successfully-emerges-financial).','', 'This changed the 100-stock result from 26.22% original / 27.51% buffer to **32.58% / 30.20%**, reversing the buffer advantage. The corrected full current-roster test completed at **28.79% / 29.25%**. These current-roster cohorts remain survivor-selected. The result is sensitive to security identity and cohort composition; the higher returns do not establish a more reliable edge. The original data and results remain in the artifact bundle; corrected forecasts are in `identity-sensitivity/`. This correction has not been promoted into the frozen forward-study dependency chain.','', '## Different market periods','',
 'Historical S&P portfolio period returns, not annualized; 2019 and 2021 are partial years. This is a descriptive breakdown of the same frozen test, not three independent holdouts.','',
 '| Period | Original HGB | Buffer | SPY |','|---|---:|---:|---:|']
 for year,label in [('2019','Mar–Dec 2019'),('2020','2020'),('2021','Jan–Sep 3, 2021')]:
  lines.append('| '+label+' | '+' | '.join(pct(x['historical-early']['costs']['11'][m]['annual_returns'][year]) for m in ['hgb','hgb_buffer','SPY'])+' |')
 lines+=['','![Earlier history comparison](comparison.png)','',
 '## Corporate actions handled','',
 'The valuation engine now processes cash separately from successor securities. It applies documented exchange ratios, translates raw-share entitlements into the saved adjusted-price units, and retains fractional shares. Cash consideration incurs no invented stock-sale fee. Simultaneous events use pre-event holdings, preventing Raytheon merger recipients from incorrectly receiving the UTC spin-offs. Neither features nor frozen forecasts were rewritten. Cash is recognized as an entitlement at conversion and assumed available by the next monthly rebalance; actual broker settlement and fractional-share cash-in-lieu are not modeled.','',
 '- RHT: $190 cash per share. [IBM completion notice](https://uk.newsroom.ibm.com/2019-07-09-IBM-Closes-Landmark-Acquisition-of-Red-Hat-for-34-Billion-Defines-Open-Hybrid-Cloud-Future).',
 '- APC: $59 cash plus 0.2934 OXY shares. [Occidental filing](https://www.sec.gov/Archives/edgar/data/797468/000079746820000004/oxy10k12-31x2019.htm).',
 '- CELG: $50 cash, one BMY share and one traded contingent-value right. The right has observed prices under provider symbol BMY.RT; it was not discarded. [BMS completion notice](https://investors.bms.com/iframes/press-releases/press-release-details/2019/Bristol-Myers-Squibb-Completes-Acquisition-of-Celgene-Creating-a-Leading-Biopharma-Company/default.aspx).',
 '- STI: 1.295 TFC shares. [Truist filing](https://www.sec.gov/Archives/edgar/data/92230/000009223020000045/tfc-20191231.htm).',
 '- RTN: 2.3348 RTX shares. UTC spin-off entitlement rules separately retain one CARR and one-half OTIS share per UTC share; those distributions do not belong to former RTN holders. [RTX filing](https://www.sec.gov/Archives/edgar/data/101829/000114036120008397/nc10010681x2_8k.htm).',
 '- AGN: $120.30 cash plus 0.866 ABBV shares. [Exchange removal filing](https://www.sec.gov/Archives/edgar/data/876661/000087666120000384/ruleprovisionnotice.htm).',
 '- NBL: 0.1191 CVX shares; CXO: 1.46 COP shares. Archived provider corporate-action records and [Chevron investor information](https://www.chevron.com/investors/stock-and-dividend?q=chevron+texaco+merger), [ConocoPhillips completion notice](https://www.conocophillips.com/news-media/story/conocophillips-completes-acquisition-of-concho-resources/).',
 '- DISCA/DISCK: one WBD share each. CTRA: 0.70 DVN shares. These allow the later reconstruction to advance past its prior Discovery block. [Discovery filing](https://www.sec.gov/Archives/edgar/data/1437107/000119312522103051/d328161d8k.htm), [Devon completion filing](https://www.sec.gov/Archives/edgar/data/1090012/000119312526211971/d799973d8k.htm).','',
 'The original strategy actually held seven merger names in the earlier historical cohort; the buffer held eight, adding APC. Other prepared conversions are applied only when the relevant security is held.','',
 '## Unresolved data, not a wait for new market days','',
 '- **Historical 2021–2026:** now stops on April 10, 2023 at SBNY and SIVB. SIVB subsequently traded as SIVBQ. FRC/FRCB is another later required gap. The configured Alpaca OTC requests returned HTTP 403; authorization/subscription coverage for that historical feed is unavailable through these requests. The exact failure receipts are retained. No sale price or zero write-off was invented.',
 '- **Original current S&P roster 2019–2021:** stopped July 1, 2020 at EXE-labelled predecessor history; the separate current-security inception correction now allows this comparison to complete. Chesapeake traded as CHKAQ after its 2020 delisting and its old equity was later cancelled. Old equity and newly issued successor stock must not be treated as a continuous investment. [Contemporaneous SEC filing](https://www.sec.gov/Archives/edgar/data/895126/000089512620000131/a8-k2020x06x298xkreini.htm), [cancellation filing](https://www.sec.gov/Archives/edgar/data/895126/000089512621000078/chk-20201231.htm). CHKAQ OTC data was also requested and returned HTTP 403. Such data is required to reconstruct old Chesapeake holders, not to pretend cancelled shares are the current security.',
 '- **Daily risk coverage:** the historical early portfolio lacks one BIIB open, retained as a valuation gap. Its drawdown covers observed marks; volatility, Sharpe and beta requiring a complete daily series are withheld.',
 '- **Broader qualification:** dated community membership is better suited to this question than today\'s roster, but 239 historical issuer mappings and sector vintages remain unqualified in the source panel. These specific merger repairs do not certify the entire historical security master.','',
 'To finish the blocked 2021–2026 historical comparison, supply an authorized historical OTC source covering SBNY/SIVBQ in March–April 2023 and FRCB in May 2023, then reconcile the remaining terminal events and identities. Broader reconstruction of old Chesapeake holders also needs CHKAQ data in June–July 2020. Nothing about these requirements depends on tomorrow\'s prices.','',
 '## Verification and reproducibility','',
 f'- {len(v["causal_refits"])} first/middle/last HGB refits across three universes produced identical scores after all future prices were removed.',
 '- 38 focused unit/regression tests passed, including cash entitlements, adjustment-factor units, missing successor prices, and simultaneous merger/spin-off ordering.',
 '- Six additional causal refits of the corrected inputs passed, with all non-EXE observations verified unchanged.',
 '- All frozen target hashes and four event-panel hashes verified. Six no-event portfolios reproduce the original independently audited accounting.',
 '- All 24 initial event-accounting runs and 12 identity-corrected strategy/cost runs match between bisection and independent fixed-point transaction-cost solvers. This is a separate cost-solver replay; both use the same tested corporate-action processing code.',
 '- The first scorer attempt found an audit-schema mismatch on incomplete portfolios. `scorer-amendment.json` records the corrected comparison direction and preserves the original source; no predictions, thresholds or targets changed.',
 '- `protocol.json`, `targets-lock.json`, `event-accounting-lock.json`, raw captures, source documents, `results.json`, `event-results.json`, `verification.json`, and `unit-tests.xml` retain the full evidence. `manifest.json` hashes the final artifact bundle.','',
 'The frozen forward study remains a separate comparison. No model or trading-rule change was made to improve these retrospective results.']
 (r/'report.md').write_text('\n'.join(lines)+'\n')
 with (r/'summary.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
 fig,axes=plt.subplots(1,3,figsize=(18,5),sharey=True)
 colors={'hgb':'#333333','hgb_buffer':'#098fae','SPY':'#999999'}
 for ax,(key,title) in zip(axes,[('diverse100-early','Current-roster diverse 100'),('sp500-early','Current S&P roster'),('historical-early','Dated historical S&P membership')]):
  dates=[z['date'] for z in x[key]['costs']['11']['SPY']['curve']]
  for m,z in x[key]['costs']['11'].items():
   by={v['date']:v['equity']*100000 for v in z['curve']}
   ax.plot([datetime.fromisoformat(d) for d in dates],[by.get(d,np.nan) for d in dates],label={'hgb':'Original HGB','hgb_buffer':'HGB + buffer','SPY':'SPY'}[m],color=colors[m],linewidth=1.8)
  ax.set_title(title);ax.grid(alpha=.2);ax.legend();ax.tick_params(axis='x',rotation=25)
 axes[0].set_ylabel('Value of $100,000 after modeled costs')
 fig.suptitle('March 2019–September 2021 • fixed rules • 11 bps per traded side')
 fig.tight_layout();fig.savefig(r/'comparison.png',dpi=150);fig.savefig(r/'comparison.svg');plt.close(fig)
 for path in [Path(__file__),Path('scripts/research/validate_prediction_history.py'),Path('scripts/research/reconcile_prediction_history.py'),Path('scripts/research/prediction_event_accounting.py'),Path('scripts/research/prediction_identity_sensitivity.py'),Path('tests/research/test_prediction_event_accounting.py')]:
  (r/'code'/path.name).write_bytes(path.read_bytes())
 manifest={str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(r.rglob('*')) if p.is_file() and p.name!='manifest.json'}
 (r/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(r/'report.md')

if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);main(ap.parse_args().root)
