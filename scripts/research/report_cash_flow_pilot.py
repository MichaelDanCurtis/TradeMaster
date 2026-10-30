"""Render the frozen O1 evidence, keeping feasibility and performance distinct."""
import argparse,hashlib
from pathlib import Path
from datetime import date
import numpy as np
from scripts.research.event_research_pilot import read,write_new,digest,now


def run(root):
    assert all(digest(root/n)==h for n,h in read(root/'pre-score-lock.json').items())
    assert all(digest(root/n)==h for n,h in read(root/'manifest.json').items())
    d=read(root/'results.json');events=sorted([read(root/n) for n in read(root/'targets-lock.json')],key=lambda e:e['entry'])
    labels={'SPY':'SPY buy and hold','cash_flow':'Cash-flow overlay','momentum':'Momentum overlay','matched':'Sector/liquidity/momentum-matched overlay'}
    lines=['# Institutional cash-flow pilot: first result','',
      'This frozen three-event cash-flow proxy did not beat SPY, matched controls, or the typical shuffled-cash portfolio. It is not a deployment candidate. No new data subscription was purchased and no broker orders were submitted.','',
      '## Whole-account result','',
      'July 10, 2019–April 30, 2021. During each of three ten-session windows, the strategy allocated 20% to ten equal-weight destination stocks and 80% to SPY; otherwise it held 100% SPY. The table includes entry, rotation and final liquidation costs. Annualized returns summarize this mostly-SPY account, not a standalone cash-flow strategy.','',
      '| Portfolio | CAGR, 11 bps/side | CAGR, 22 bps/side | $100,000 ending wealth, 11 bps |',
      '|---|---:|---:|---:|']
    for n,label in labels.items():
        a,b=d['results'][n]['11'],d['results'][n]['22'];assert a['state']==b['state']=='complete' and not a['valuation_gaps'] and not b['valuation_gaps']
        lines.append(f"| {label} | {a['cagr']:.2%} | {b['cagr']:.2%} | ${100000*(1+a['net_return']):,.0f} |")
    lines+=['','At either cost assumption, 79 of 100 cash-allocation shuffles performed at least as well as the real ownership linkage. Shuffles preserve total hypothetical cash within manager reported-equity size quintiles. They are conditional diagnostics, not 100 independent historical events or a significance claim.','',
      '## Individual event windows','',
      'These diagnostic returns start and liquidate a fresh 80% SPY / 20% sleeve portfolio over each event window, at 11 bps per side. They must not be summed as continuous account performance.','',
      '| Acquisition | Entry / exit | Cash-flow portfolio return | SPY return | Difference | Cash-holding managers retained |',
      '|---|---|---:|---:|---:|---:|']
    for e in events:
        a=d['event_diagnostics']['cash_flow'][e['id']]['net_return'];b=d['event_diagnostics']['SPY'][e['id']]['net_return']
        lines.append(f"| {e['id']} | {e['entry']} / {e['exit']} | {a:.2%} | {b:.2%} | {(a-b)*100:+.2f} pp | {e['cash_holders']} |")
    lines+=['','## What was built and checked','',
      '- Seven SEC historical 13F filing archives, with originals retained and hashed. Separately captured, dated raw pre-event bars supply dollar-volume features; future-adjusted price levels are not used for that denominator.',
      '- Latest publicly filed reports within 180 days. Amendments, multiple originals, confidentiality flags, shared-discretion managers and duplicate common-stock CUSIPs are excluded under fixed rules.',
      '- Hypothetical cash equals reported target shares times the confirmed per-share consideration. Destination allocation follows the manager’s other disclosed common-equity weights and is divided by trailing dollar volume. Unmapped or unmatched weight stays unallocated.',
      '- An initial bulk review found issuer-name/CUSIP inconsistencies. A versioned pre-outcome revision requires row-level name agreement. The original targets and code remain preserved; neither version was tuned against returns.',
      '- Independent scalar graph arithmetic, timing and ranking checks passed before scoring. Primary portfolio replays matched a separate transaction-cost solver. Six focused graph tests passed, covering units, duplicates, timing, shuffles and false issuer labels.',
      '- Every primary and shuffled replay completed. Original selected stocks, source files and pre-score hashes remain unchanged.','',
      '## Coverage and limitations','',
      '| Event | Qualifying graph managers | Positive-flow candidate stocks | Hypothetical target cash represented |',
      '|---|---:|---:|---:|']
    for e in events:lines.append(f"| {e['id']} | {e['graph_managers']} | {e['positive_flow_destinations']} | ${e['hypothetical_cash_usd']:,.0f} |")
    lines+=['','These dollar amounts are modeled from lagged reports. They are not observed payments, incremental buying or sums to invest. The report does not establish that those target holdings survived until completion, that one fund owned both positions, or that recipients reinvested proportionally.','',
      'The issuer announced/confirmed completion and cash terms, but individual beneficial-owner payment dates are unobserved. The rule therefore tests a completion-triggered coholding proxy, not certified cash-arrival timing. Historical security mapping uses unique normalized company names and common-share CUSIPs against a dated community S&P archive; it is not a certified security master. Strict matching sharply reduces coverage, especially Tiffany and Varian. Current SEC bulk files have been reprocessed, and historical sector labels can incorporate later corrections.','',
      'Only three deliberately named acquisitions are included. They are feasibility cases chosen without inspecting their outcomes, not a complete event population or untouched holdout. Controls match sector, liquidity and momentum; liquidity is not market capitalization, and stock-financed-merger controls have not been run. Adjusted historical opening prices are simulation observations, not verified executable broker fills. Taxes and actual settlement are not simulated.','',
      '## Research decision','',
      'Do not promote or tune this exact proportional-cash rule on these outcomes. The expected ownership linkage failed its first controls. Keep the reusable graph/capture tools, while leaving the broader institutional cash-flow mechanism unproven. A wider study would first need stronger issuer coverage and independently dated payment/ownership evidence; no paid data purchase is implied. Existing forward research and paper-account observation plans are unchanged.','',
      '## Primary event sources','',
      '- [IBM: completed Red Hat acquisition, $190 per share](https://www.ibm.com/investor/news/ibm-completes-acquisition-of-red-hat).',
      '- [Tiffany final 8-K: January 7 completion and $131.50 per share](https://www.sec.gov/Archives/edgar/data/98246/000119312521004213/d301758d8k.htm).',
      '- [Siemens Healthineers: Varian completion](https://www.siemens-healthineers.com/press/releases/varian-closing) and [$177.50 cash terms](https://www.siemens-healthineers.com/press/releases/august3.html).','',
      f'Frozen artifacts: `{root}`. `protocol.json`, `pre-outcome-revision.json`, `pre-score-verification.json`, `*-targets.json`, `results.json` and raw capture receipts preserve the research sequence.','']
    with (root/'report.md').open('x') as f:f.write('\n'.join(lines))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    fig,axes=plt.subplots(1,2,figsize=(12,5.5),gridspec_kw={'width_ratios':[1.25,1]})
    for n,color in [('cash_flow','#117f8c'),('matched','#ba8330')]:
        a=d['results'][n]['11'];spy=d['results']['SPY']['11'];assert [x['date'] for x in a['curve']]==[x['date'] for x in spy['curve']]
        difference=[100000*(x['equity']-y['equity']) for x,y in zip(a['curve'],spy['curve'])]
        axes[0].plot([date.fromisoformat(x['date']) for x in a['curve']],difference,label=labels[n].replace('Sector/liquidity/momentum-matched','Matched'),color=color,lw=1.7)
    axes[0].axhline(0,color='#777',lw=.8);axes[0].set_title('Wealth difference from SPY');axes[0].yaxis.set_major_formatter(FuncFormatter(lambda x,_:f'${x:,.0f}'));axes[0].legend(frameon=False,fontsize=8)
    shuffled=[100000*(d['results'][f'shuffle_{i:03}']['11']['net_return']-d['results']['SPY']['11']['net_return']) for i in range(100)]
    actual=100000*(d['results']['cash_flow']['11']['net_return']-d['results']['SPY']['11']['net_return'])
    axes[1].hist(shuffled,bins=15,color='#bbc9d1',edgecolor='white');axes[1].axvline(actual,color='#117f8c',lw=2,label='Actual linkage');axes[1].axvline(0,color='#777',lw=.8);axes[1].set_title('100 shuffled-cash controls');axes[1].xaxis.set_major_formatter(FuncFormatter(lambda x,_:f'${x:,.0f}'));axes[1].set_xlabel('Ending wealth difference from SPY');axes[1].legend(frameon=False,fontsize=8)
    for ax in axes:ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.15)
    fig.suptitle('Cash-flow pilot: no improvement over SPY',fontsize=18,x=.07,ha='left')
    fig.text(.07,.025,'$100,000 starting wealth • 11 bps per side • 20% event sleeve, SPY otherwise\nThree selected events; manager holdings/payment assumptions and identity coverage limit the result.',fontsize=9,color='#555')
    fig.autofmt_xdate(rotation=25);fig.subplots_adjust(bottom=.22,top=.83,left=.08,right=.97,wspace=.27);fig.savefig(root/'comparison.png',dpi=150);fig.savefig(root/'comparison.svg');plt.close(fig)
    write_new(root/'report-manifest.json',{n:digest(root/n) for n in ['report.md','comparison.png','comparison.svg']})
    print('Verified frozen inputs and wrote report and chart')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
