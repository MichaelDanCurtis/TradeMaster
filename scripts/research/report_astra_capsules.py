"""Write the sealed Astra experiment's results and reproducibility report."""
import argparse,csv,json,hashlib,shutil
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import date

LABELS={'astra':'Astra blinded','ridge':'Ridge','hgb':'HGB','momentum_12_1':'12-1 momentum','equal_weight':'Equal weight','SPY':'SPY buy & hold','cash':'Cash'}
def pct(v):return 'unavailable' if v is None else f'{100*v:.2f}%'
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();root=a.root;r=json.loads((root/'results.json').read_text());cases=json.loads((root/'private/cases.json').read_text());decisions={c['case_id']:json.loads((root/'decisions'/f"{c['case_id']}.json").read_text()) for c in cases}
 lines=['# Astra historical decision experiment','',
 'A fresh GPT-6 Astra agent made each of 60 monthly decisions for both stock universes. Ticker names and calendar dates were hidden in the main run. Six additional agents saw the same six selected historical snapshots with tickers and dates visible. All 66 decisions were saved and hashed before this experiment was scored.','',
 'In this price/volume exercise, Astra did not establish a stock-selection advantage: both portfolios finished below SPY, equal weight, simple momentum, and the trained ranking models. Astra had shallower drawdowns on observed prices. The 95% intervals for its average excess return versus SPY include zero.','',
 '**Scope:** September 7, 2021 opening prices through September 4, 2026 opening prices; 59 full 21-session holds and one shortened final hold. Each agent selected the top third of eligible stocks, held equally weighted. The 100-stock cohort spans 11 sectors; the larger cohort uses a fixed current S&P roster of 503 securities representing 500 companies. Incomplete trailing histories reduce eligibility.','',
 '## Five-year results','',
 'All returns below include assumed commissions and slippage of 11 basis points per side, with a doubled-cost sensitivity. These are adjusted-price, fractional-share research simulations. Cash earns zero; taxes are excluded. The frozen Ridge/HGB comparisons use the prior corporate-action quarantine sensitivity, without changing evaluation prices or rules.','',
 '| Universe | Strategy | Total net return | Annualized return | Worst drawdown | Annualized at 22 bps/side |','|---|---|---:|---:|---:|---:|']
 flat=[]
 for u,ur in r['universes'].items():
  for m,p in ur['costs']['11'].items():
   q=ur['costs']['22'][m]
   lines.append(f"| {'Diverse 100' if u=='diverse100' else 'S&P roster'} | {LABELS[m]} | {pct(p.get('net_return'))} | {pct(p.get('cagr'))} | {pct(p.get('max_drawdown'))} | {pct(q.get('cagr'))} |")
  for cost,ps in ur['costs'].items():
   for m,p in ps.items():flat.append({'universe':u,'model':m,'cost_bps_per_side':cost,**{k:p.get(k) for k in ['state','net_return','cagr','max_drawdown','annualized_volatility','beta_to_SPY','fees_fraction_initial_capital','two_sided_turnover_sum']}})
 with (root/'summary.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
 fig,axes=plt.subplots(1,2,figsize=(13,5),layout='constrained');colors={'astra':'#118ab2','ridge':'#7b2cbf','hgb':'#ef8354','SPY':'#222222','equal_weight':'#9e9e9e','momentum_12_1':'#2a9d8f'}
 for ax,(u,ur) in zip(axes,r['universes'].items()):
  for m in ['astra','ridge','hgb','momentum_12_1','equal_weight','SPY']:
   p=ur['costs']['11'][m]
   if p['state']!='complete':continue
   ax.plot([date.fromisoformat(x['date']) for x in p['curve']],[100000*x['equity'] for x in p['curve']],label=LABELS[m],color=colors[m],linewidth=2.4 if m=='astra' else 1.3,alpha=1 if m in ['astra','SPY'] else .8)
  ax.set_title('Diverse 100' if u=='diverse100' else 'Current S&P roster');ax.set_ylabel('Value of $100,000, net of modeled costs');ax.grid(alpha=.18);ax.ticklabel_format(axis='y',style='plain');ax.legend(fontsize=8)
 fig.suptitle('Fresh Astra decisions • five-year retrospective • 11 bps per side');fig.savefig(root/'comparison.png',dpi=170);fig.savefig(root/'comparison.svg');plt.close(fig)
 lines+=['','![Portfolio comparison](comparison.png)','','## Excess-return uncertainty','','Mean excess return per complete holding period, with a circular 3-period block bootstrap (5,000 samples, fixed seed). The final shortened hold is excluded. Intervals are exploratory and unadjusted for the broader research program’s multiple comparisons.','','| Universe | Astra versus | Mean excess per period | 95% interval |','|---|---|---:|---:|']
 for u,ur in r['universes'].items():
  p=ur['costs']['11']['astra']
  for c in ['SPY','equal_weight','ridge','hgb','momentum_12_1']:
   v=p.get('paired_period_excess_vs_'+c)
   if v:lines.append(f"| {u} | {LABELS[c]} | {pct(v['mean'])} | [{pct(v['interval95'][0])}, {pct(v['interval95'][1])}] |")
 lines+=['','## How different were the selections?','','Average fraction of Astra holdings also selected by each frozen quantitative rule. This describes decision similarity, not return attribution.','','| Universe | Ridge overlap | HGB overlap | Momentum overlap |','|---|---:|---:|---:|']
 for u,ur in r['universes'].items():
  o=ur['decision_overlap'];lines.append(f"| {u} | {pct(o['ridge']['mean_selected_overlap_fraction'])} | {pct(o['hgb']['mean_selected_overlap_fraction'])} | {pct(o['momentum_12_1']['mean_selected_overlap_fraction'])} |")
 lines+=['','## Named versus blinded controls','','Each row is a separate round-trip holding period at 11 bps per side. These six scattered observations are not a five-year named-stock portfolio. Different responses can arise from normal model variability as well as recognizable history; this is not a causal estimate of hindsight contamination.','','| Cutoff | Universe | Blinded return | Named return | Selection overlap |','|---|---|---:|---:|---:|']
 for p in r['named_pairs']:
  v=p['costs']['11'];lines.append(f"| {p['date']}{' (partial hold)' if p['truncated'] else ''} | {p['universe']} | {pct(v['blind'].get('net_return'))} | {pct(v['named'].get('net_return'))} | {pct(p['overlap_fraction'])} |")
 lines+=['','## Evidence boundaries and verification','',
 '- Every agent was assigned its own packet and a common decision contract in a fresh conversation, with explicit instructions not to cheat, use hindsight, browse, read other files, or infer hidden identities and dates. Local arithmetic on the packet was allowed. These are instruction-level boundaries on a shared filesystem, not an operating-system sandbox.',
 '- Fresh forks still received Codex’s automatic memory summary. It mentioned the prior TimesFM/Chronos study and that Chronos-2 failed simple baselines. All 66 summaries had the same hash; a finite keyword check found no wider Ridge/HGB result references. This is additional retrospective context, so the experiment is not a clean-room simulation. The limitation was documented before scoring; no decisions were discarded or rerun.',
 '- Parent dispatch receipts confirm 66 distinct tasks with fork_turns=none and model gpt-6-astra. Their task-message bodies are encrypted in stored logs; the plaintext common contract and observable commands are retained, but exact task text cannot be independently recovered from those receipts.',
 '- Two independent reviewers inspected all 137 recorded tool inputs and all 66 local Python programs. They found no forbidden evidence requests. Five initial relative-path reads were retried with absolute paths; the parent verified original missing-file error outputs, retained in relative-path-retry-receipts.json.',
 '- The model’s learned history cannot be erased. We cannot prove a historically uncontaminated GPT-6 existed in 2021. Self-attestations and blinded identifiers reduce or document risks; they do not remove them.',
 '- Packets contain ten past price/volume features and past SPY context. This measures price/volume portfolio selection, not full company research with historical news, filings, analyst estimates, or a point-in-time fundamentals archive. No future realized prices or existing strategy predictions were supplied.',
 '- Packet checks reproduce all 66 inputs and match each universe to the earlier quantitative experiment. Tests that remove all future data leave tested packets unchanged. Six focused automated tests cover causality, eligibility, identity masking, count validation, and choice translation.',
 '- All decisions are frozen before scoring; translated holdings preserve exactly the selected stocks. Independent accounting replays use a different transaction-cost solver and verify all four main portfolio/cost cases plus 24 individual named/blinded holding cases.',
 '- Current-roster survivorship bias and revised adjusted data remain. The corporate-action sensitivity quarantines questionable pre-test training history; it does not create authentic historical constituent membership or vintage prices.',
 '- Astra received rounded raw stock features and past SPY context. Ridge/HGB use cross-sectionally ranked stock features and matured historical training labels. This is a workflow comparison, not a controlled comparison with equal training information.',
 '- One model, one decision per date, no performance-based retries. The 60 dates are dependent market observations, not 60 independent model trials. The top-third fully invested mandate limits how an agent could manage risk.',
 '- No broker orders, paper-trial configuration, or live execution controls were changed.']
 for u,ur in r['universes'].items():
  p=ur['costs']['11']['astra']
  if p.get('valuation_gaps'):lines.append(f"- {u}: {len(p['valuation_gaps'])} missing intraperiod marks were omitted without inventing prices; held units persisted. Daily volatility/Sharpe/beta are unavailable; drawdown covers observed marks.")
 lines+=['','## Decision audit trail','','The machine-readable files retain every selection, rationale, formula, confidence statement, and hindsight disclosure. The table below indexes those records; IDs can be resolved using the evaluator-only mapping after the experiment.','','| Case | Diverse count | S&P count | Confidence (100 / S&P) | Hindsight disclosure |','|---|---:|---:|---|---|']
 for c in cases:
  cid=c['case_id'];d=decisions[cid];dis=d['hindsight_disclosure'].replace('|','/').replace('\n',' ')
  lines.append(f"| [{cid}](decisions/{cid}.json) | {len(d['diverse100']['selected_ids'])} | {len(d['sp500']['selected_ids'])} | {d['diverse100']['confidence']} / {d['sp500']['confidence']} | {dis} |")
 lines+=['','## Files','','- `protocol.json`, `decision-contract.txt`: declared experiment and common agent instructions.','- `context-limitations.json`: pre-scoring disclosure of automatic retrospective project context.','- `packets/`, `private/cases.json`, `packet-verification.json`: supplied evidence, evaluator mappings, causality checks.','- `decisions/`, `decisions-frozen.json`: immutable selections and pre-scoring hashes.','- `access-audit.json`, `access-review-*.json`, `spawn-receipts.json`, `context-limitations.json`: observable tool calls, independent access reviews, dispatch metadata and automatic context limitations.','- `predictions-*.json`, `results.json`, `summary.csv`: translated holdings, audited financial results, compact comparison.','- `code/`, `manifest.json`: reproducibility source snapshot and file hashes.','']
 (root/'report.md').write_text('\n'.join(lines))
 for name in ['prepare_astra_capsules.py','evaluate_astra_capsules.py','report_astra_capsules.py','prediction_wide_portfolios.py','prediction_portfolios.py','verify_prediction_wide.py','audit_astra_access.py']:
  shutil.copy2(Path(__file__).parent/name,root/'code'/name)
 manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file() and p.name!='manifest.json'}
 (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(root/'report.md')
if __name__=='__main__':main()
