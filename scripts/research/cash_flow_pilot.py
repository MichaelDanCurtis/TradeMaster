"""Frozen, no-new-subscription three-event cash-flow feasibility experiment."""
import argparse,csv,io,json,zipfile,hashlib,time,copy
from collections import defaultdict,Counter
from pathlib import Path
from datetime import datetime,timezone
import httpx
import numpy as np
from scripts.research.event_research_pilot import read,write_new,digest,now
from tradingagents.research.cash_flow_graph import day,company_key,common,eligible_reports,build_graph,shuffled_cash

PANEL=Path('.research-artifacts/prediction-historical-validation-2026-09-07/historical-early-event-panel.json')
HISTORY=Path('.research-artifacts/filing-free-identity-audit-2026-09-07/history-source/components_history.csv')
QUARTERS=['2019q1','2019q2','2019q3','2020q3','2020q4','2021q1','2021q2']
EVENTS=[{'id':'RHT','company':'Red Hat Inc','cusip':'756577102','cash':190.,'announced':'2018-10-28','completed':'2019-07-09','sources':['https://www.ibm.com/investor/news/ibm-completes-acquisition-of-red-hat']},
 {'id':'TIF','company':'Tiffany & Co','cusip':'886547108','cash':131.5,'announced':'2019-11-25','terms_revised':'2020-10-28','completed':'2021-01-07','sources':['https://www.sec.gov/Archives/edgar/data/98246/000119312521004213/d301758d8k.htm']},
 {'id':'VAR','company':'Varian Medical Systems Inc','cusip':'92220P105','cash':177.5,'announced':'2020-08-02','completed':'2021-04-15','sources':['https://www.siemens-healthineers.com/press/releases/varian-closing','https://www.siemens-healthineers.com/press/releases/august3.html']}]


def freeze(root):
    root.mkdir(parents=True,exist_ok=False);(root/'archives').mkdir()
    write_new(root/'protocol.json',{'id':'O1-three-event-proxy-v2','frozen_at':now(),'events':EVENTS,'quarters':QUARTERS,
      'sources':{str(p):digest(p) for p in [PANEL,HISTORY]},'code':{str(p):digest(p) for p in [Path(__file__),Path('tradingagents/research/cash_flow_graph.py'),Path('scripts/research/score_cash_flow_pilot.py'),Path('scripts/research/prediction_event_accounting.py'),Path('scripts/research/prediction_portfolios.py'),Path('scripts/research/verify_prediction_wide.py')]},
      'rules':{'ownership':'Latest public report within 180 days; filing date through completion day, available at EOD. Amendments/multiple originals/confidential disclosures excluded. Sole-discretion managers only; duplicate common CUSIP excludes manager.',
       'scope':'Completion-triggered hypothetical redeployment from lagged manager reports. Not observed receipt or fund-level reinvestment. Three deliberately named feasibility cases, not population-wide or untouched validation.',
       'payment_date':'Beneficial-owner payment dates unobserved. Completion is a public event trigger, not a certified same-day cash receipt.',
       'identity':'Unique normalized issuer name plus common class joins to dated public S&P archive; ambiguous issuer/class/CIK excluded. Candidate mapping, not certified CUSIP security master. Target cash requires exact normalized issuer-name/CUSIP agreement per row; destination demand uses only individually matching name/CUSIP rows, leaving other weights unallocated.',
       'demand':'target reported shares times merger cash times each other common holding value / all other disclosed common-equity value; unmapped weight stays unallocated; divide destination demand by trailing 20-session dollar volume.',
       'eligibility':'Dated membership and unique historical issuer mapping; 60 prior complete daily closes, prior 20 volumes, positive demand; never select using future prices.',
       'portfolio':'20% sleeve, equal weight top 10 demand/ADV stocks; 80% SPY. Hold 10 opening-to-opening sessions starting next session after completion-day EOD; otherwise 100% SPY.',
       'controls':['SPY buy-hold','20% sleeve top-10 prior 60-session momentum','20% sleeve sector-matched price-volume controls','100 cash shuffles within manager reported-equity size quintiles, seeds 0..99'],
       'matched_control':'For each selected stock, three nearest unselected same-sector destinations by squared log ADV ratio plus squared 60-session-return difference / .1; equal over three, aggregated sleeve; incomplete if no candidates.',
       'cost_bps_per_side':[11,22],'minimum_mapped_stocks':30,'minimum_cash_holders':20,'shuffle_count':100,
       'decision':'No deployment from three events. Reject a promotable result if it trails SPY after costs or does not exceed matched and shuffled controls. Missing post-selection endpoints remain incomplete.'},
      'new_data_subscription_budget_usd':0,'limitations':['Current reprocessed SEC bulk archive; public filing-date lag, not receipt-time vintage certification','Historical sector labels may be revised','Manager is not fund; sole discretion does not prove no affiliate duplication','No stock-financed event control in this small feasibility stage','Whole-account SPY overlay is a separately frozen implementation choice; not the original institutional paper replication']})


def check(root):
    p=read(root/'protocol.json')
    assert all(digest(f)==h for f,h in {**p['sources'],**p['code']}.items()),'Frozen dependency changed'
    return p


def capture(root):
    p=check(root);receipts={}
    with httpx.Client(timeout=90,follow_redirects=True,headers={'User-Agent':'TradeMasterResearch/1.0 personal desktop research'}) as client:
        for q in p['quarters']:
            path=root/'archives'/f'{q}.zip';url=f'https://www.sec.gov/files/structureddata/data/form-13f-data-sets/{q}_form13f.zip'
            if path.exists():raise ValueError('Write-once capture already exists')
            if q=='2019q2':
                old=Path('.research-artifacts/public-13f-bulk-pilot-2026-09-08');receipt=next(r for r in read(old/'receipt.json').values() if r['url']==url);source=old/receipt['file'];assert digest(source)==receipt['sha256'];path.hardlink_to(source);record={'source':'prior verified capture',**receipt}
            else:
                with client.stream('GET',url) as response:
                    response.raise_for_status();size=0
                    with path.open('xb') as f:
                        for chunk in response.iter_bytes():
                            size+=len(chunk)
                            if size>256*1024**2:raise ValueError('Archive exceeds 256 MiB bound')
                            f.write(chunk)
                record={'url':url,'retrieved_at':now(),'sha256':digest(path),'bytes':size}
            receipts[q]=record;write_new(root/'archives'/f'{q}-receipt.json',record);print(q,record['bytes'],flush=True);time.sleep(.3)
    # Separate read-only dated raw bars give a dollar-volume denominator that
    # is not rescaled by future dividends or splits in the adjusted panel.
    from scripts.research.capture_prediction_improvements import Capture,provider
    (root/'prices').mkdir();headers,engine=provider();c=Capture(root/'prices',headers,.35)
    panel=read(PANEL);dates=panel['dates']
    try:
        for event in p['events']:
            end=event['completed'];idx=dates.index(end);names=sorted(historical_names(end,panel))
            for j in range(0,len(names),50):
                params={'symbols':','.join(names[j:j+50]),'start':dates[idx-65], 'end':end+'T23:59:59Z','timeframe':'1Day','limit':10000,'sort':'asc','adjustment':'raw','asof':end,'feed':'sip','currency':'USD'}
                for page in range(10):
                    result=c.get('https://data.alpaca.markets/v2/stocks/bars',dict(params),f"{event['id']}-{j:03}-{page}.json")
                    if result is None:raise ValueError('Raw pre-event price capture failed')
                    if not result.get('next_page_token'):break
                    params['page_token']=result['next_page_token']
                else:raise ValueError('Unexpected raw-bar pagination')
            print('pre-event raw prices',event['id'],len(names),flush=True)
    finally:c.client.close();engine.dispose()
    write_new(root/'capture-lock.json' ,{q:digest(root/'archives'/f'{q}.zip') for q in p['quarters']})


def table(archive,name):
    return csv.DictReader(io.TextIOWrapper(archive.open(name),encoding='utf-8-sig'),delimiter='\t')


def historical_names(day_,panel):
    grouped=defaultdict(list)
    for r in csv.DictReader(HISTORY.open()):
        start=max(r['created_at'],r['date_added'].rstrip('*'));end=r['date_removed'].rstrip('*')
        symbol=r['symbol'].replace('.','-')
        if start<=day_ and (not end or day_<end) and symbol in panel['symbols']:grouped[symbol].append(r)
    return {s:v[0] for s,v in grouped.items() if len({r['cik'] for r in v})==1}


def targets(root):
    p=check(root);assert all(digest(root/'archives'/f'{q}.zip')==h for q,h in read(root/'capture-lock.json').items())
    # Reading the cached panel here is restricted to pre-event eligibility/features;
    # endpoint values are accessed only by the separate score stage.
    panel=read(PANEL);dates=panel['dates'];symbols=panel['symbols'];submissions={};covers={};source_by_acc={}
    for q in p['quarters']:
        with zipfile.ZipFile(root/'archives'/f'{q}.zip') as z:
            for s in table(z,'SUBMISSION.tsv'):
                acc=s['ACCESSION_NUMBER'];assert acc not in submissions or submissions[acc]==s;submissions[acc]=s;source_by_acc[acc]=q
            covers.update({r['ACCESSION_NUMBER']:r for r in table(z,'COVERPAGE.tsv')})
    all_events=[]
    for event in p['events']:
        cutoff=event['completed'];eligible,exclusions=eligible_reports(submissions,covers,cutoff)
        rows=defaultdict(list);catalog=defaultdict(set);names_by_cusip=defaultdict(set)
        for q in p['quarters']:
            if not any(source_by_acc[a]==q for a in eligible):continue
            with zipfile.ZipFile(root/'archives'/f'{q}.zip') as z:
                for r in table(z,'INFOTABLE.tsv'):
                    a=r['ACCESSION_NUMBER']
                    if a not in eligible:continue
                    rows[eligible[a]['manager']].append(r)
                    if common(r):catalog[company_key(r['NAMEOFISSUER'])].add(r['CUSIP']);names_by_cusip[r['CUSIP']].add(r['NAMEOFISSUER'])
        assert event['cusip'] in names_by_cusip,'Target CUSIP missing'
        raw_prices={}
        price_receipt=read(root/'prices/receipt.json')['responses']
        for path in sorted((root/'prices').glob(event['id']+'-*.json')):
            assert digest(path)==price_receipt[path.name]['sha256']
            for symbol,bars in read(path)['bars'].items():
                raw_prices.setdefault(symbol,{}).update({b['t'][:10]:b for b in bars if b['t'][:10]<=cutoff})
        named=historical_names(cutoff,panel);company_symbols=defaultdict(list)
        for s,r in named.items():company_symbols[company_key(r['name'])].append(s)
        t=dates.index(cutoff);entry=t+1;exit_=entry+10;mapping=[];mapping_excluded=[]
        for key,stocks in sorted(company_symbols.items()):
            cusips=catalog.get(key,set())
            if len(stocks)!=1 or len(cusips)!=1:
                mapping_excluded.append({'symbols':stocks,'reason':'ambiguous_or_no_exact_common_name_match','cusips':sorted(cusips)});continue
            s=stocks[0];c=next(iter(cusips));i=symbols.index(s)
            if c==event['cusip'] or s==panel['benchmark'] or not panel['membership'][t][i]:continue
            declared=panel['issuers'].get(s,'')
            if str(declared).isdigit() and int(declared)!=int(named[s]['cik']):
                mapping_excluded.append({'symbols':[s],'reason':'issuer_cik_conflict'});continue
            close=panel['series'][s]['close'];volume=panel['series'][s]['volume'];history=close[t-60:t+1]
            if len(history)!=61 or any(x is None or not np.isfinite(x) or x<=0 for x in history):continue
            raw=[raw_prices.get(s,{}).get(d) for d in dates[t-19:t+1]]
            if len(raw)!=20 or any(b is None or b['v']<=0 or b['c']<=0 for b in raw):continue
            adv=float(np.mean([b['c']*b['v'] for b in raw]));momentum=float(close[t]/close[t-60]-1)
            mapping.append({'symbol':s,'cusip':c,'issuer_name':named[s]['name'],'cik':named[s]['cik'],'reported_labels':sorted(names_by_cusip[c]),'sector':named[s]['sector'],'adv20':adv,'momentum60':momentum})
        counts=Counter(x['cusip'] for x in mapping);mapping=[x for x in mapping if counts[x['cusip']]==1]
        graph=build_graph(rows,event['cusip'],[m['cusip'] for m in mapping],event['cash'],target_key=company_key(event['company']),destination_keys={m['cusip']:company_key(m['issuer_name']) for m in mapping})
        demand=graph['cash']@graph['weights'];candidates=[j for j in range(len(mapping)) if demand[j]>0]
        assert len(candidates)>=p['rules']['minimum_mapped_stocks'],('too_few_destinations',event['id'],len(candidates))
        assert len(graph['cash_owners'])>=p['rules']['minimum_cash_holders'],('too_few_owners',event['id'],len(graph['cash_owners']))
        adv=np.array([m['adv20'] for m in mapping]);scores=demand/adv
        ranked=lambda vector:sorted(candidates,key=lambda j:(-float(vector[j]),mapping[j]['symbol']))[:10]
        chosen=ranked(scores);momentum=ranked(np.array([m['momentum60'] for m in mapping]));matched=defaultdict(float);match_missing=[]
        for j in chosen:
            m=mapping[j];pool=[k for k in candidates if k not in chosen and mapping[k]['sector']==m['sector']]
            near=sorted(pool,key=lambda k:((np.log(mapping[k]['adv20']/m['adv20']))**2+((mapping[k]['momentum60']-m['momentum60'])/.1)**2,mapping[k]['symbol']))[:3]
            if not near:match_missing.append(m['symbol']);continue
            for k in near:matched[mapping[k]['symbol']]+=.2/10/len(near)
        portfolios={'cash_flow':{mapping[j]['symbol']:.02 for j in chosen},'momentum':{mapping[j]['symbol']:.02 for j in momentum},'matched':dict(matched)}
        for seed in range(p['rules']['shuffle_count']):
            shuffled=shuffled_cash(graph['cash'],graph['aum'],seed)@graph['weights']/adv
            portfolios[f'shuffle_{seed:03}']={mapping[j]['symbol']:.02 for j in ranked(shuffled)}
        manifest={**event,'entry':dates[entry],'exit':dates[exit_],'entry_index':entry,'exit_index':exit_,'report_exclusions':exclusions,'manager_exclusions':graph['exclusions'],'eligible_reports':len(eligible),'graph_managers':len(graph['managers']),'cash_holders':len(graph['cash_owners']),'hypothetical_cash_usd':float(sum(graph['cash'])),'mapped_hypothetical_cash_usd':float(sum(demand)),'destinations':len(mapping),'positive_flow_destinations':len(candidates),'mapping_excluded':mapping_excluded,'target_labels':sorted(names_by_cusip[event['cusip']]),'mapping':[{**m,'demand_usd':float(demand[j]),'demand_adv':float(scores[j])} for j,m in enumerate(mapping)],'portfolios':portfolios,'matched_missing':match_missing,'report_selection':eligible,'cash_owners':graph['cash_owners']}
        np.savez_compressed(root/f"{event['id']}-graph.npz",weights=graph['weights'],cash=graph['cash'],aum=graph['aum'],managers=graph['managers'])
        write_new(root/f"{event['id']}-targets.json",manifest);all_events.append(manifest)
        print(json.dumps({k:manifest[k] for k in ['id','entry','exit','eligible_reports','graph_managers','cash_holders','destinations','positive_flow_destinations','hypothetical_cash_usd','matched_missing']}),flush=True)
    write_new(root/'targets-lock.json',{x.name:digest(x) for x in root.glob('*-targets.json')})

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['freeze','capture','targets']);ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();globals()[a.stage](a.root)
