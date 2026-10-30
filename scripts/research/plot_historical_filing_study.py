"""Plot completed, continuously valued historical portfolios; never fill gaps."""
import argparse
from pathlib import Path
from datetime import date
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from scripts.research.event_research_pilot import read


def run(root):
    data=read(root/'results.json')['results']
    labels={'filing_stability':'Filing stability','eligible_equal_weight':'Same eligible stocks, equal weight','SPY_buy_hold':'SPY buy and hold'}
    colors={'filing_stability':'#177e89','eligible_equal_weight':'#b28704','SPY_buy_hold':'#7540a8'}
    fig,ax=plt.subplots(figsize=(12,6.5));shown=0
    for name,label in labels.items():
        r=data[name]['11']
        if r['state']!='complete' or r.get('valuation_gaps'):continue
        ax.plot([date.fromisoformat(x['date']) for x in r['curve']],
                [100000*x['equity'] for x in r['curve']],label=f"{label} ({r['cagr']:.1%} CAGR)",color=colors[name],linewidth=2)
        shown+=1
    if not shown:
        plt.close(fig);raise ValueError('No complete, continuously valued portfolio to plot')
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x,_:f'${x/1000:,.0f}k'))
    ax.grid(axis='y',alpha=.2);ax.spines[['top','right']].set_visible(False)
    ax.set_title('Historical filing-stability test',loc='left',fontsize=19,pad=30)
    ax.text(0,1.025,'$100,000 starting capital • 11 bps per traded side • dividends included in source prices',transform=ax.transAxes,fontsize=10)
    ax.legend(frameon=False,loc='upper left')
    fig.text(.08,.035,'Exploratory, previously examined period under three years. Only completed curves without valuation gaps are shown.\nCommunity identity/membership sources and corporate-action assumptions remain qualification limits.',fontsize=9,color='#555555')
    fig.subplots_adjust(bottom=.17,top=.83,left=.08,right=.97)
    fig.savefig(root/'comparison.png',dpi=160);fig.savefig(root/'comparison.svg');plt.close(fig)
    print('Saved comparison.png and comparison.svg')


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
