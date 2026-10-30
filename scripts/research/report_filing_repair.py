"""Audit the valuation-only amendment and report its qualified outcome."""
import argparse, json, math
from pathlib import Path
from datetime import date
from scripts.research.event_research_pilot import read, write_new, digest, now


def run(root):
    protocol=read(root/'protocol.json');parent=Path(protocol['parent'])
    assert all(digest(p)==h for p,h in protocol['inputs'].items())
    assert all(digest(p)==h for p,h in protocol['code'].items())
    assert all(digest(root/p)==h for p,h in read(root/'manifest.json').items())
    cfg=read(parent/'protocol.json');original=read(cfg['panel']);amended=read(root/'panel.json')
    assert original['symbols']==amended['symbols'] and original['dates']==amended['dates']
    for s,series in original['series'].items():
        if s!='AZN':assert series==amended['series'][s],s
    assert original['valuation_only_reconciliation']['events']==amended['valuation_only_reconciliation']['events'][:-1]
    event=read(root/'event.json');assert amended['valuation_only_reconciliation']['events'][-1]==event
    data=read(root/'results.json')['results'];prior=read(parent/'results.json')['results']
    for bps,spy in data['SPY_buy_hold'].items():
        assert set(prior['SPY_buy_hold'][bps])-set(spy)=={'beta_to_spy','excess_cagr_to_spy'}
        assert all(v==prior['SPY_buy_hold'][bps][k] for k,v in spy.items())
    for result in data['filing_stability'].values():
        assert result['state']=='complete'
        assert result['valuation_gaps']==[{'date':'2020-11-06','symbols':['BIIB']}]
        item=next(x for x in result['corporate_actions'] if x['old']=='ALXN')
        assert math.isclose(item['cash_credit'],item['raw_share_equivalent']*60)
        assert math.isclose(item['delivered_adjusted_units']['AZN']*event['successors'][0]['adjustment_factor'],item['raw_share_equivalent']*2.1243)
    write_new(root/'verification.json',{'verified_at':now(),'input_and_artifact_hashes':'passed','original_non_AZN_price_series':'unchanged',
      'original_events':'unchanged; one ALXN event appended','benchmark':'identical to original replay','cash_and_ADS_entitlement_arithmetic':'passed',
      'BIIB_halt':'only remaining daily valuation gap; no fill','model_selections':'parent targets preserved','scope':'Structural and arithmetic audit; not comprehensive security-master or settlement certification'})
    lines=['# Historical filing-stability result','',
      'The completed terminal-wealth replay did not beat SPY. This is an exploratory result for April 1, 2019–September 3, 2021, not a three-year or out-of-sample qualification. No new subscription was purchased.','',
      '| Trading cost per side | Filing stability CAGR | SPY CAGR | Difference | $100,000: strategy / SPY |',
      '|---|---:|---:|---:|---:|']
    for bps,a in data['filing_stability'].items():
        b=data['SPY_buy_hold'][bps]
        lines.append(f"| {bps} bps | {a['cagr']:.2%} | {b['cagr']:.2%} | {(a['cagr']-b['cagr'])*100:.2f} pp | ${100000*(1+a['net_return']):,.0f} / ${100000*(1+b['net_return']):,.0f} |")
    lines+=['','The strategy held the highest-stability third of eligible issuers, in equal weights, at ten frozen quarterly decisions. Eligible counts were 477–493; selected counts were 159–165. Signals came from 5,274 structurally qualified filing pairs out of 5,479 candidates, using 7,542 original documents. Availability delays and selections were checked independently of return calculations.','',
      '## Accounting repair','',
      'The first replay could not finish because ALXN disappeared after its acquisition. This amendment preserves that first result and all stock selections. Each old raw ALXN share converts to $60 cash and 2.1243 AZN ADS entitlements at the July 21, 2021 completion. Newly captured AZN prices value the delivered interest. No rebalance occurs until September 3, after the new ADS began trading July 22. Cash is credited at economic conversion; fractional entitlements are retained. This is not an exact brokerage settlement simulation.','',
      '[OCC conversion terms](https://infomemo.theocc.com/infomemos?number=49014) and [issuer completion announcement](https://www.astrazeneca.com/media-centre/press-releases/2021/acquisition-of-alexion-completed.html) support the event. Direct HTTP downloads returned 403; public web-tool extracts and the response-status receipts are archived separately. No original-PDF capture is claimed.','',
      '## Remaining limitations','',
      '- BIIB was halted on November 6, 2020. That daily valuation is missing; no trade price was invented. Terminal wealth completes, but daily volatility, Sharpe and beta are not qualified. Observed maximum drawdown was approximately 36.28%, versus 32.05% for SPY; missing marks can understate maximum drawdown. [OCC halt notice](https://infomemo.theocc.com/infomemos?number=47809).',
      '- The same-eligible-stocks equal-weight control remains incomplete because several other historical corporate actions need reconciliation, beginning with L3. It cannot yet establish whether this signal adds stock-selection value. The full-membership control also has unresolved identity/date conflicts.',
      '- Community historical issuer/membership mappings and adjusted provider prices are not a fully certified point-in-time security master. Thirteen stock/date identity conflicts were excluded from filing eligibility and explicitly block the full-universe control.',
      '- This previously examined period is under three years. It does not test the rolling 36-month target, untouched generalization, live execution, taxes, or every settlement detail.','',
      '## Decision','',
      'Do not promote this F1 equal-weight variant to trading or tune it against this outcome. Its observed whole-account result is below SPY. Leave signal attribution unproven until the matched control is repaired. Keep the separately frozen forward and paper trials unchanged. The free institutional-ownership source pilot is ready for a separately frozen hypothesis and historical test; it has no return evidence yet.','',
      '## Evidence','',f'- Frozen source run: `{parent}`',f'- Valuation amendment: `{root}`',
      '- `results.json`: both transaction-cost replays and full ledgers.',
      '- `verification.json`: unchanged inputs, unaffected prices, benchmark equality and entitlement arithmetic.',
      '- `comparison.png`: observed daily marks with a visible gap on the halt date.',
      '- Prior failed capture/environment attempts are retained; no stock-selection change occurred.','']
    with (root/'report.md').open('x') as f:f.write('\n'.join(lines))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    fig,ax=plt.subplots(figsize=(11,6));days=amended['dates'];start=data['SPY_buy_hold']['11']['first_date'];end=data['SPY_buy_hold']['11']['last_date'];days=[d for d in days if start<=d<=end]
    for name,label,color in [('filing_stability','Filing stability','#087f8c'),('SPY_buy_hold','SPY buy and hold','#7443a3')]:
        result=data[name]['11'];marks={x['date']:100000*x['equity'] for x in result['curve']}
        ax.plot([date.fromisoformat(d) for d in days],[marks.get(d,float('nan')) for d in days],label=f"{label}: {result['cagr']:.2%} CAGR",color=color,lw=1.8)
    ax.axvline(date(2020,11,6),color='#999',ls=':',lw=.8)
    ax.set_title('Filing stability fell short of SPY in this test',loc='left',fontsize=17,pad=25)
    ax.text(0,1.02,'April 2019–September 2021 • $100,000 starting wealth • 11 bps per traded side',transform=ax.transAxes,fontsize=10)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x,_:f'${x/1000:,.0f}k'));ax.grid(axis='y',alpha=.2);ax.legend(frameon=False);ax.spines[['top','right']].set_visible(False)
    fig.text(.09,.03,'Exploratory and under three years. Dotted line: BIIB halt; missing strategy mark is not filled.\nEconomic merger entitlements; historical identity and settlement limits remain. Matched control incomplete.',fontsize=9,color='#555')
    fig.subplots_adjust(bottom=.17,top=.85,left=.09,right=.97);fig.savefig(root/'comparison.png',dpi=150);fig.savefig(root/'comparison.svg');plt.close(fig)
    write_new(root/'report-manifest.json',{n:digest(root/n) for n in ['verification.json','report.md','comparison.png','comparison.svg']})
    print('Verified valuation amendment and wrote report/plots')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
