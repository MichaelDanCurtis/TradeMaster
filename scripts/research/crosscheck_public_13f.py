"""Compare three deterministic bulk-archive samples with original SEC XML."""
import argparse,csv,io,json,zipfile,hashlib
from collections import Counter
from decimal import Decimal
from pathlib import Path
from lxml import etree
from scripts.research.event_research_pilot import Capture,read,write_new,digest,now
from tradingagents.research.filing_identity import local


def field(node,name):
    values=[' '.join(' '.join(n.itertext()).split()) for n in node.iter() if local(n.tag)==name.lower()]
    if len(values)>1:raise ValueError('Ambiguous XML field '+name)
    return values[0] if values else ''


def number(s):return str(Decimal(s.replace(',','')).normalize())


def key(r):
    return (r['NAMEOFISSUER'].upper().strip(),r['TITLEOFCLASS'].upper().strip(),r['CUSIP'].strip(),
            number(r['VALUE']),number(r['SSHPRNAMT']),r['SSHPRNAMTTYPE'].upper(),r['PUTCALL'].upper(),r['INVESTMENTDISCRETION'].upper())


def run(parent):
    audit=read(parent/'audit.json');root=parent/'original-crosscheck';root.mkdir();(root/'raw').mkdir()
    bymanager={x['manager_cik']:x['accession'] for x in audit['red_hat_examples']}
    chosen=sorted(bymanager,key=lambda c:hashlib.sha256(('O1-public-2019Q2:'+c).encode()).hexdigest())[:3]
    selected={bymanager[c]:c for c in chosen}
    write_new(root/'protocol.json',{'created_at':now(),'selected_accessions':selected,
      'selection':'Three Red Hat-reporting managers by SHA256(O1-public-2019Q2:CIK); no outcome data',
      'parent_audit_sha256':digest(parent/'audit.json'),'code_sha256':digest(Path(__file__)),
      'comparison':'Multiset of issuer/class/CUSIP/value/share count/share type/option type/discretion across full original information tables; do not compare only Red Hat rows'})
    receipt=read(parent/'receipt.json');zpath=next(parent/x['file'] for x in receipt.values() if x['url'].endswith('.zip'))
    expected={a:Counter() for a in selected}
    with zipfile.ZipFile(zpath) as z:
        name=next(n for n in z.namelist() if Path(n).name.upper()=='INFOTABLE.TSV')
        for r in csv.DictReader(io.TextIOWrapper(z.open(name),encoding='utf-8-sig'),delimiter='\t'):
            if r['ACCESSION_NUMBER'] in expected:expected[r['ACCESSION_NUMBER']][key(r)]+=1
    cfg={'headers':{'User-Agent':'TradeMasterResearch/1.0 personal desktop research'},'minimum_request_spacing_seconds':1,'workers':1,'max_attempts':3}
    c=Capture(root,cfg);results=[]
    try:
        for accession,cik in selected.items():
            base=f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-","")}'
            idx=c.get(base+'/index.json')
            if idx is None:raise ValueError('Original index unavailable')
            actual=Counter();tables=[];headers=[]
            for item in json.loads(idx)['directory']['item']:
                name=item['name']
                import re
                if not re.fullmatch(r'[A-Za-z0-9_.-]+\.xml',name,re.I):continue
                raw=c.get(base+'/'+name)
                if raw is None:continue
                t=etree.fromstring(raw,parser=etree.XMLParser(resolve_entities=False,no_network=True))
                if local(t.tag)=='informationtable':
                    tables.append(name)
                    for node in t:
                        if local(node.tag)!='infotable':continue
                        r={k:field(node,v) for k,v in {'NAMEOFISSUER':'nameOfIssuer','TITLEOFCLASS':'titleOfClass','CUSIP':'cusip','VALUE':'value','SSHPRNAMT':'sshPrnamt','SSHPRNAMTTYPE':'sshPrnamtType','PUTCALL':'putCall','INVESTMENTDISCRETION':'investmentDiscretion'}.items()}
                        actual[key(r)]+=1
                elif local(t.tag)=='edgarsubmission':
                    headers.append({'filename':name,'submission_type':field(t,'submissionType'),
                                    'report_date':field(t,'reportCalendarOrQuarter')})
            result={'accession':accession,'manager_cik':cik,'tables':tables,'headers':headers,
                    'bulk_rows':sum(expected[accession].values()),'original_rows':sum(actual.values()),
                    'positions_match':actual==expected[accession] and len(tables)==1,
                    'missing_bulk_rows':sum((actual-expected[accession]).values()),
                    'extra_bulk_rows':sum((expected[accession]-actual).values())}
            results.append(result)
    finally:c.close()
    write_new(root/'results.json',{'checked_at':now(),'samples':results,
       'passed':all(r['positions_match'] for r in results),
       'scope':'Three original-source spot checks; not certification of the entire bulk archive or economically deduplicated ownership'})
    write_new(root/'manifest.json',{str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file()})
    print(json.dumps(results),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
