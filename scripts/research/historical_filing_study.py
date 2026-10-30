"""Public-data F1-SP500-EW study. Freeze, capture, select, then value separately."""
import argparse
from bisect import bisect_right
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from lxml import etree
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from scripts.research.event_research_pilot import Capture, digest, now, read, write_new
from tradingagents.research.filing_stability import (
    original_pairs, submission_rows, document_url, normalized_document,
    conservative_public_time, score_pair, sha_bytes, validate_document,
)
from tradingagents.research.filing_identity import scoped_identity
from tradingagents.research.historical_filings import instance_identity, choose_portfolio, historical_inline_identity

PANEL = Path('.research-artifacts/prediction-historical-validation-2026-09-07/historical-early-event-panel.json')
CALENDAR = Path('.research-artifacts/prediction-wide-2026-09-07/capture/raw/calendar.json')
CODE = [Path(__file__).resolve(), *[Path('tradingagents/research/'+n+'.py').resolve() for n in
        ['historical_filings','filing_stability','filing_identity']],
        *[Path('scripts/research/'+n+'.py').resolve() for n in ['event_research_pilot', 'prediction_event_accounting', 'prediction_portfolios', 'verify_prediction_wide', 'evaluate_astra_capsules']]]


def check(root):
    p = read(root/'protocol.json')
    if digest(root/'protocol.json') != read(root/'protocol-lock.json')['sha256']:
        raise ValueError('Protocol changed')
    for f,h in p['hashes'].items():
        if digest(Path(f)) != h: raise ValueError('Frozen input changed: '+f)
    return p


def freeze(root, identity_file=None):
    panel = read(PANEL); calendar = read(CALENDAR)
    dates = panel['dates']
    entries = [next(d for d in dates if d >= f'{y}-{m:02d}-01')
               for y in [2019,2020,2021] for m in [1,4,7,10]
               if '2019-04-01' <= f'{y}-{m:02d}-01' <= '2021-07-01']
    universes = []
    for d in entries:
        i = dates.index(d)
        universes.append({'date': d, 'membership_asof': dates[i-1],
                          'members': [s for s,flag in zip(panel['symbols'],panel['membership'][i-1]) if flag]})
    symbols = sorted({s for u in universes for s in u['members']})
    identity = read(identity_file) if identity_file else None
    issuer_map={s:panel['issuers'][s] for s in symbols}
    extra_inputs=[]
    if identity:
        if set(identity['candidates'])!=set(symbols):raise ValueError('Identity universe differs')
        for s,x in identity['candidates'].items():
            if str(issuer_map[s]).isdigit() and issuer_map[s]!=x['cik']:raise ValueError('Conflicting CIK')
            issuer_map[s]=x['cik']
        source=Path(identity['source'])
        if digest(source)!=identity['source_sha256']:raise ValueError('Identity source changed')
        extra_inputs=[identity_file,source,Path('scripts/research/prepare_historical_filing_identities.py')]
        for d in universes:
            d['identity_conflicts']=[x['symbol'] for x in identity['date_conflicts'] if x['membership_asof']==d['membership_asof']]
    root.mkdir(parents=True,exist_ok=False)
    for name in ['raw','metadata','documents','normalized']: (root/name).mkdir()
    write_new(root/'universe.json', {'decisions':universes, 'issuers':issuer_map,
              'source':panel['membership_source'], 'scope':panel['universe_scope']})
    p={'id':'F1-SP500-EW-v1','data_revision':'r2_public_historical_identifiers' if identity else 'inherited_mapping','identity_source':str(identity_file) if identity_file else None,'frozen_at':now(),'new_data_subscription_budget_usd':0,
       'hashes':{str(x.resolve()):digest(x) for x in [PANEL,CALENDAR,*CODE,*extra_inputs,root/'universe.json']},
       'panel':str(PANEL.resolve()),'calendar':str(CALENDAR.resolve()),'entries':entries,'liquidation':'2021-09-03',
       'rules':{'signal':'Original same-fiscal-period annual Jaccard filing stability; fixed existing normalization',
                'identity':'Context-bound inline DEI, or non-dimensional DEI in same-accession separate XBRL instance',
                'new_report_years':[2018,2019,2020,2021],'freshness_days':180,
                'availability':'max(acceptance UTC, filing-day NY end)+5 minutes; then two full exchange sessions',
                'selection':'Latest available structurally valid pair per issuer; top ceil(N/3); equal weight',
                'membership':'Previous session historical community reconstruction; no future outcome screen',
                'share_classes':'Lexicographically first eligible member per CIK; stable tie break by CIK then symbol',
                'controls':['eligible equal weight','full historical membership equal weight','SPY buy hold'],
                'costs_bps_per_side':[11,22],'missing':'No removal based on future missing price; incomplete accounting is reported',
                'no_eligible':'Hold cash, report coverage; never substitute an unqualified signal'},
       'limitations':['Previously examined historical interval, not an untouched holdout',
                       'Less than 36 months; cannot establish rolling three-year goal',
                       'Inherited current-derived CIK mapping and community membership have coverage/lineage limitations',
                       'Existing corporate-action economic entitlements and fractional-share assumptions are reused'],
       'sec':{'headers':{'User-Agent':'TradeMasterResearch/1.0 personal desktop research','Accept-Encoding':'gzip, deflate'},
              'minimum_request_spacing_seconds':.2,'workers':4,'max_attempts':3}}
    write_new(root/'protocol.json',p);write_new(root/'protocol-lock.json',{'sha256':digest(root/'protocol.json')})
    print(json.dumps({'frozen':str(root),'decisions':len(entries),'symbols':len(symbols),
                      'mapped':sum(str(issuer_map[s]).isdigit() for s in symbols)}),flush=True)


def metadata(root):
    p=check(root); u=read(root/'universe.json'); c=Capture(root,p['sec'])
    ciks=sorted({v for v in u['issuers'].values() if str(v).isdigit()})
    def fetch(cik):
        f=root/'metadata'/f'{cik}.json'
        if f.exists(): return
        raw=c.get(f'https://data.sec.gov/submissions/CIK{cik}.json')
        rows=[];issues=[]
        if raw is None: issues.append('submissions_unavailable')
        else:
            d=json.loads(raw)
            if int(d['cik']) != int(cik): raise ValueError('CIK response mismatch')
            rows=submission_rows(d,cik)
            for older in d['filings'].get('files',[]):
                if older['filingTo']<'2017-01-01' or older['filingFrom']>'2021-09-03': continue
                if not re.fullmatch(r'CIK\d{10}-submissions-\d+\.json',older['name']): raise ValueError('Unsafe history path')
                r=c.get('https://data.sec.gov/submissions/'+older['name'])
                if r is None: issues.append('history_unavailable:'+older['name'])
                else: rows+=submission_rows(json.loads(r),cik)
        unique={}
        for r in rows:
            k=r['accessionNumber']
            if k in unique and unique[k]!=r: raise ValueError('Conflicting accession')
            unique[k]=r
        write_new(f,{'cik':cik,'rows':list(unique.values()),'issues':issues})
    try:
        with ThreadPoolExecutor(max_workers=p['sec']['workers']) as pool:list(pool.map(fetch,ciks))
    finally:c.close()
    print(json.dumps({'metadata_complete':len(ciks)}),flush=True)


def plans(root):
    p=check(root);u=read(root/'universe.json');cal=read(Path(p['calendar']))
    opens=[datetime.fromisoformat(r['date']+'T'+r['open']).replace(tzinfo=ZoneInfo('America/New_York')) for r in cal]
    def usable(r):
        k=bisect_right(opens,conservative_public_time(r)+timedelta(seconds=300))+2
        return cal[k]['date'] if k<len(cal) else None
    relevant={}
    for d in u['decisions']:
        for s in d['members']:
            relevant.setdefault(u['issuers'][s],[]).append(d['date'])
    pairs=[];issues=[]
    for cik,decisions in sorted(relevant.items()):
        if not str(cik).isdigit():continue
        m=read(root/'metadata'/f'{cik}.json');issues.extend({'cik':cik,'issue':x} for x in m['issues'])
        for year in p['rules']['new_report_years']:
            for pair in original_pairs(m['rows'],report_year=year,limit_per_issuer=8):
                try:entry=usable(pair['new'])
                except (ValueError,KeyError,TypeError):entry=None
                if not entry:continue
                applicable=[d for d in sorted(set(decisions)) if entry<=d and
                    0 <= (datetime.fromisoformat(d)-datetime.fromisoformat(pair['new']['filingDate'])).days <=180]
                if applicable:pairs.append({**pair,'eligible_entry_date':entry,'decisions':applicable})
    write_new(root/'pairs.json',{'pairs':pairs,'metadata_issues':issues})
    write_new(root/'pairs-lock.json',{'sha256':digest(root/'pairs.json'),
               'metadata_hashes':{x.name:digest(x) for x in (root/'metadata').glob('*.json')}})
    print(json.dumps({'candidate_pairs':len(pairs),'unique_documents':len({r['accessionNumber'] for pair in pairs for r in [pair['new'],pair['old']] if r})}),flush=True)


def check_pairs(root):
    lock=read(root/'pairs-lock.json')
    if digest(root/'pairs.json')!=lock['sha256']:raise ValueError('Pairs changed')
    for n,h in lock['metadata_hashes'].items():
        if digest(root/'metadata'/n)!=h:raise ValueError('Metadata changed')
    return read(root/'pairs.json')['pairs']


def capture_documents(root,limit=None):
    p=check(root);pairs=check_pairs(root);c=Capture(root,p['sec'])
    unique={(r['cik'],r['accessionNumber']):r for pair in pairs for r in [pair['new'],pair['old']] if r}
    records=sorted(unique.values(),key=lambda r:(r['filingDate'],r['cik'],r['accessionNumber']))
    if limit is not None:records=records[:limit]
    def fetch(r):
        target=root/'documents'/(r['cik']+'_'+r['accessionNumber']+'.json')
        if target.exists():return
        url=document_url(r);raw=c.get(url)
        out={'record':r,'status':'unavailable','primary_url':url,'raw_sha256':None}
        if raw is None:write_new(target,out);return
        out['raw_sha256']=sha_bytes(raw)
        # The old HTML may have no inline XBRL. Fetch only the same accession's instance.
        identity=historical_inline_identity(raw,r)
        if len(identity['dei'])<5:
            base=url.rsplit('/',1)[0]
            # primary documents may have nested names; accession directory is authoritative.
            base=f"https://www.sec.gov/Archives/edgar/data/{int(r['cik'])}/{r['accessionNumber'].replace('-','')}"
            idx=c.get(base+'/index.json'); candidates=[]
            if idx is not None:
                for item in json.loads(idx)['directory']['item']:
                    name=item['name']
                    if (re.fullmatch(r'[A-Za-z0-9_.-]+\.xml',name,re.I)
                        and not re.search(r'_(cal|def|lab|pre)\.xml$',name,re.I)
                        and name.lower() not in {'filingsummary.xml','metalinks.xml'}
                        and not re.fullmatch(r'R\d+\.xml',name,re.I)):
                        candidates.append(name)
            alternatives=[]
            for name in sorted(candidates):
                xml=c.get(base+'/'+name)
                if xml is None:continue
                try:parsed=instance_identity(xml,r)
                except (ValueError, etree.XMLSyntaxError) as exc:
                    # XML parsing errors become a document coverage issue, never an inferred identity.
                    out.setdefault('instance_errors',[]).append({'file':name,'error':type(exc).__name__});continue
                if len(parsed['dei'])==5:
                    alternatives.append({**parsed,'source_url':base+'/'+name,'sha256':sha_bytes(xml)})
            if len(alternatives)==1:identity=alternatives[0]
            elif alternatives:out['identity_issue']='ambiguous_external_instances'
        out['identity']=identity;out['status']='captured'
        write_new(target,out)
    try:
        with ThreadPoolExecutor(max_workers=p['sec']['workers']) as pool:list(pool.map(fetch,records))
    finally:c.close()
    print(json.dumps({'documents_processed':len(records),'total_required':len(unique)}),flush=True)


def normalize_one(task):
    root, f, rec = task
    d=read(f);dest=root/'normalized'/f.name
    if dest.exists() or d['status']!='captured':return
    raw=(root/rec['file']).read_bytes()
    if sha_bytes(raw)!=d['raw_sha256']:raise ValueError('Raw changed')
    n=normalized_document(raw);n['dei']=d['identity']['dei'];n['record']=d['record']
    n['identity_issue']=d.get('identity_issue');write_new(dest,n)


def normalize(root):
    check(root);pairs=check_pairs(root);receipt=read(root/'receipt.json')
    byhash={x.get('sha256'):x for x in receipt.values() if x.get('sha256')}
    tasks=[]
    for f in sorted((root/'documents').glob('*.json')):
        d=read(f)
        if d['status']=='captured' and not (root/'normalized'/f.name).exists():
            tasks.append((root,f,byhash[d['raw_sha256']]))
    with ProcessPoolExecutor(max_workers=4) as pool:
        for i,_ in enumerate(pool.map(normalize_one,tasks),1):
            if i%25==0:print(json.dumps({'normalized':i,'pending_batch':len(tasks)}),flush=True)
    out=[]
    for pair in pairs:
        docs=[]
        for r in [pair['new'],pair['old']]:
            f=root/'normalized'/((r['cik']+'_'+r['accessionNumber'] if r else 'missing')+'.json')
            if f.exists():docs.append(read(f))
        result={'status':'unqualified','issues':['missing_original_or_normalized_document'],'jaccard':None}
        if len(docs)==2:
            if any(d.get('identity_issue') for d in docs):
                result['issues']=['ambiguous_external_instances']
            else:result=score_pair(pair,*docs)
        out.append({**pair,**result})
    write_new(root/'signals.json',{'pairs':out,'counts':dict(Counter(x['status'] for x in out))})
    write_new(root/'signals-lock.json',{'sha256':digest(root/'signals.json'),
        'document_hashes':{str(x.relative_to(root)):digest(x) for folder in ['documents','normalized'] for x in (root/folder).glob('*.json')}})
    print(json.dumps({'signals':dict(Counter(x['status'] for x in out))}),flush=True)


def targets(root):
    p=check(root);u=read(root/'universe.json');lock=read(root/'signals-lock.json')
    if digest(root/'signals.json')!=lock['sha256']:raise ValueError('Signals changed')
    for f,h in lock['document_hashes'].items():
        if digest(root/f)!=h:raise ValueError('Normalized document changed')
    pairs=read(root/'signals.json')['pairs'];results=[]
    for d in u['decisions']:
        issuer_map=dict(u['issuers'])
        for s in d.get('identity_conflicts',[]):issuer_map[s]='DATE_CONFLICT:'+s
        result=choose_portfolio(d['members'],issuer_map,pairs,d['date'])
        result['identity_date_conflicts']=d.get('identity_conflicts',[])
        results.append(result)
    write_new(root/'targets.json',{'decisions':results,'rules':p['rules'],'return_labels_used':False})
    write_new(root/'targets-lock.json',{'sha256':digest(root/'targets.json'),'signals_sha256':lock['sha256']})
    print(json.dumps({'eligible_counts':[len(x['eligible']) for x in results],
                      'selected_counts':[len(x['selected']) for x in results]}),flush=True)


def score(root):
    import numpy as np
    from scripts.research.prediction_event_accounting import simulate_events
    from scripts.research.evaluate_astra_capsules import compare_recursive
    p=check(root);check_pairs(root)
    if digest(root/'targets.json')!=read(root/'targets-lock.json')['sha256']:raise ValueError('Targets changed')
    panel=read(Path(p['panel']));decisions=read(root/'targets.json')['decisions'];u=read(root/'universe.json')
    symbols=panel['symbols'];positions={s:i for i,s in enumerate(symbols)};dates=panel['dates']
    events=panel['valuation_only_reconciliation']['events'];out={}
    for variant in ['filing_stability','eligible_equal_weight','full_membership_equal_weight','SPY_buy_hold']:
        rows=[]
        for j,d in enumerate(decisions):
            selected=(d['selected'] if variant=='filing_stability' else
                      [x['symbol'] for x in d['eligible']] if variant=='eligible_equal_weight' else
                      u['decisions'][j]['members'] if variant=='full_membership_equal_weight' else [panel['benchmark']])
            w=[0.]*(len(symbols)+1)
            for s in selected:w[-1 if s==panel['benchmark'] else positions[s]]=1/len(selected)
            rows.append({'entry_index':dates.index(d['date']),
                         'exit_index':dates.index(decisions[j+1]['date'] if j+1<len(decisions) else p['liquidation']),
                         'target_weights':w})
        if variant=='SPY_buy_hold':rows=[{**rows[0],'exit_index':rows[-1]['exit_index']}]
        out[variant]={}
        for bps in p['rules']['costs_bps_per_side']:
            conflicts=[d for d in u['decisions'] if d.get('identity_conflicts')]
            if variant=='full_membership_equal_weight' and conflicts:
                out[variant][str(bps)]={'state':'incomplete','date':conflicts[0]['date'],
                   'unresolved_symbols':conflicts[0]['identity_conflicts'],
                   'reason':'Historical identity/date conflict between public sources; full-universe valuation not qualified',
                   'valuation_gaps':[],'curve':[]}
                print(json.dumps({'variant':variant,'state':'incomplete_identity','unresolved':conflicts[0]['identity_conflicts']}),flush=True)
                continue
            a=simulate_events(panel,rows,events,bps/10000)
            b=simulate_events(panel,rows,events,bps/10000,audit=True);compare_recursive(a,b)
            out[variant][str(bps)]=a
            print(json.dumps({'variant':variant,'cost_bps':bps,'state':a['state'],'cagr':a.get('cagr'),
                              'gaps':len(a.get('valuation_gaps',[])),'unresolved':a.get('unresolved_symbols')}),flush=True)
    for bps in p['rules']['costs_bps_per_side']:
        spy=out['SPY_buy_hold'][str(bps)]
        for name,rows in out.items():
            a=rows[str(bps)]
            if a['state']=='complete' and not a['valuation_gaps'] and spy['state']=='complete':
                r=np.array(a['daily_returns']);s=np.array(spy['daily_returns'])
                a['beta_to_spy']=float(np.cov(r,s,ddof=1)[0,1]/s.var(ddof=1))
                a['excess_cagr_to_spy']=a['cagr']-spy['cagr']
    write_new(root/'results.json',{'results':out,'qualification':p['limitations'],
              'independent_trade_replay':'passed; shared event sequencing engine, separate rebalance arithmetic'})
    write_new(root/'manifest.json',{str(x.relative_to(root)):digest(x) for x in root.rglob('*') if x.is_file() and x.name!='manifest.json'})


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['freeze','metadata','plans','capture','normalize','targets','score'])
    ap.add_argument('--root',type=Path,required=True);ap.add_argument('--limit',type=int);ap.add_argument('--identities',type=Path)
    a=ap.parse_args()
    if a.stage=='capture':capture_documents(a.root,a.limit)
    elif a.stage=='freeze':freeze(a.root,a.identities)
    else:globals()[a.stage](a.root)
