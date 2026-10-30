"""Render complete challenger comparison, including paired time-block uncertainty."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'.research-artifacts/forecast/challenger-benchmark'


def interval(cases):
    by_window=defaultdict(list)
    for c in cases:by_window[c['window']].append((c['mae_pct'],c['flat_mae_pct']))
    if len(by_window)!=52 or any(len(v)!=4 for v in by_window.values()):raise ValueError('Expected all four instruments in every window')
    pairs=np.array([[statistics.mean(x[0] for x in by_window[w]),statistics.mean(x[1] for x in by_window[w])] for w in sorted(by_window)])
    rng=np.random.default_rng(71397);estimates=[]
    # Moving blocks retain adjacent-window dependence and contemporaneous stocks.
    for _ in range(5000):
        starts=rng.integers(0,49,size=13);indices=np.concatenate([np.arange(i,i+4) for i in starts])
        a,b=pairs[indices].mean(axis=0);estimates.append((1-a/b)*100)
    return [float(v) for v in np.quantile(estimates,[.025,.975])]


def main():
    benchmark=ROOT/'.research-artifacts/forecast/expanded-52-window-benchmark'
    base=json.loads((benchmark/'report.json').read_text());rows=[];individual=[]
    for label,field in [('Drift baseline','drift_mae_pct'),('Flat-price baseline','flat_mae_pct')]:
        selected=[c for c in base['cases'] if c['variant']=='stock']
        rows.append({'label':label,'mae_pct':statistics.mean(c[field] for c in selected),'baseline':True})
    for variant,label in [('stock','TimesFM-3 · closes'),('market_volume','TimesFM-3 · market/volume')]:
        selected=[c for c in base['cases'] if c['variant']==variant]
        r=next(r for r in base['overall'] if r['variant']==variant)
        rows.append({'label':label,**r,'improvement_95_interval':interval(selected)})
    names={'chronos2':'Chronos-2','kronos-base':'Kronos Base','kronos-small':'Kronos Small','sundial':'Sundial'}
    sources={}
    for kind,label in names.items():
        file=OUT/kind/'scores.json';r=json.loads(file.read_text())
        sources[kind]=hashlib.sha256(file.read_bytes()).hexdigest()
        for s in r['summaries']:
            display=label+(' · market/volume' if s['variant']=='market_volume' else ' · closes' if kind in ['chronos2','sundial'] else ' · OHLCV')
            if s['symbol']=='All four':
                selected=[c for c in r['cases'] if c['variant']==s['variant']]
                rows.append({'label':display,**s,'improvement_95_interval':interval(selected)})
            else:individual.append({'label':display,**s})
    rows.sort(key=lambda r:r['mae_pct'])
    report={'scope':'Fixed52windows,three technology stocks andSPY;historical exploratory comparison.',
        'rows':rows,'per_symbol':individual,'score_hashes':sources,
        'uncertainty':'Descriptive paired moving-block bootstrap:52windows,4consecutive-window blocks,stocks retained together,5000draws,seed71397. No model-training/sample-seed uncertainty; not prospective evidence.'}
    (OUT/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# Forecast challenger results','',
        'AAPL, MSFT, NVDA and SPY; 52 five-session windows each, August 25, 2025–September 4, 2026. Every forecast uses only the preceding 256 sessions.','',
        'Error is average absolute daily price error as a percentage of the starting price. Lower is better.','',
        '| Model and inputs | Error | Improvement vs flat | Wins vs flat |','| --- | ---: | ---: | ---: |']
    for r in rows:
        improvement='—' if r.get('baseline') else f"{r['improvement_vs_flat_pct']:+.2f}%"
        wins='—' if r.get('baseline') else f"{r['wins_vs_flat']}/208"
        lines.append(f"| {r['label']} | {r['mae_pct']:.3f}% | {improvement} | {wins} |")
    lines.extend(['','## Interpretation and limits','',
        '- Chronos-2 and Sundial use native full-precision CPU models. Kronos Base is the largest released Kronos checkpoint; Small is the size control.',
        '- Kronos receives past OHLCV and volume × source VWAP as derived turnover. It is a richer input task than close-only forecasting.',
        '- Chronos uses its native median; Sundial uses the median of 20 sampled paths; Kronos uses its native average of 10 decoded paths. Settings were frozen before scoring.',
        '- Every model is evaluated on the same outcomes. Stocks and adjacent windows are correlated; the sample is not a broad-market or untouched holdout.',
        '- Current data revisions and unknown pretraining overlap remain possible. These are prediction-error results, not trading profits.',
        '- Files include exact model revisions, input/output hashes, fixed seeds and per-case results. Runtime memory is per-process; concurrent runs are not a controlled speed comparison.','',
        '## Uncertainty of improvement over flat','',
        'Descriptive 95% moving-block bootstrap intervals retain all four instruments together and sample blocks of four successive windows. Intervals spanning zero do not separate improvement from deterioration under this resampling.','',
        '| Model | Improvement interval |','| --- | ---: |'])
    for r in rows:
        if 'improvement_95_interval' in r:
            lo,hi=r['improvement_95_interval'];lines.append(f"| {r['label']} | {lo:+.2f}% to {hi:+.2f}% |")
    lines.extend(['','Bootstrap: 5,000 draws; seed 71397. This does not account for model-training or stochastic-seed uncertainty.'])
    (OUT/'comparison.md').write_text('\n'.join(lines)+'\n')
    fig,ax=plt.subplots(figsize=(11,6.4));positions=np.arange(len(rows))
    ax.barh(positions,[r['mae_pct'] for r in rows],color=['#526574' if r.get('baseline') else '#397db7' for r in rows])
    ax.set_yticks(positions,[r['label'] for r in rows]);ax.invert_yaxis()
    flat=next(r['mae_pct'] for r in rows if r['label']=='Flat-price baseline')
    ax.axvline(flat,color='#ba4a43',linestyle='--',linewidth=1,label='Flat-price baseline')
    for i,r in enumerate(rows):ax.text(r['mae_pct']+.012,i,f"{r['mae_pct']:.3f}%",va='center',fontsize=9)
    ax.set_xlim(0,max(r['mae_pct'] for r in rows)*1.16)
    ax.set_xlabel('Average daily absolute price error / starting price (%) — lower is better')
    ax.set_title('Same-window historical forecast comparison\n52 windows × 4 instruments; 5-session forecasts',loc='left',fontweight='bold')
    ax.spines[['top','right']].set_visible(False);ax.legend(loc='lower right')
    fig.tight_layout();fig.savefig(OUT/'comparison.png',dpi=160);fig.savefig(OUT/'comparison.svg');plt.close(fig)
    print(json.dumps(rows,indent=2))

if __name__=='__main__':main()
