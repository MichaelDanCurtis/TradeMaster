"""Explain strict XML/bulk differences without changing stored source evidence."""
import argparse,csv,io,zipfile
from collections import Counter
from pathlib import Path
from lxml import etree
from scripts.research.event_research_pilot import read,write_new,digest,now
from scripts.research.crosscheck_public_13f import key,field
from tradingagents.research.filing_identity import local


def normalized(k):return tuple(' '.join(v.split()) if i in [0,1] else v for i,v in enumerate(k))


def run(root):
    p=root/'original-crosscheck';selected=read(p/'protocol.json')['selected_accessions'];expected={a:Counter() for a in selected}
    zpath=next(root/x['file'] for x in read(root/'receipt.json').values() if x['url'].endswith('.zip'))
    with zipfile.ZipFile(zpath) as z:
        name=next(n for n in z.namelist() if Path(n).name.upper()=='INFOTABLE.TSV')
        for r in csv.DictReader(io.TextIOWrapper(z.open(name),encoding='utf-8-sig'),delimiter='\t'):
            if r['ACCESSION_NUMBER'] in selected:expected[r['ACCESSION_NUMBER']][normalized(key(r))]+=1
    results=[]
    for accession,cik in selected.items():
        actual=Counter()
        for rec in read(p/'receipt.json').values():
            if accession.replace('-','') not in rec['url'] or not rec['url'].endswith('.xml'):continue
            if digest(p/rec['file'])!=rec['sha256']:raise ValueError('Original XML changed')
            t=etree.fromstring((p/rec['file']).read_bytes(),parser=etree.XMLParser(resolve_entities=False,no_network=True))
            if local(t.tag)!='informationtable':continue
            for n in t:
                if local(n.tag)!='infotable':continue
                r={k:field(n,v) for k,v in {'NAMEOFISSUER':'nameOfIssuer','TITLEOFCLASS':'titleOfClass','CUSIP':'cusip','VALUE':'value','SSHPRNAMT':'sshPrnamt','SSHPRNAMTTYPE':'sshPrnamtType','PUTCALL':'putCall','INVESTMENTDISCRETION':'investmentDiscretion'}.items()}
                actual[normalized(key(r))]+=1
        results.append({'accession':accession,'position_rows':sum(actual.values()),'match_after_label_whitespace_normalization':actual==expected[accession]})
    write_new(p/'whitespace-review.json',{'reviewed_at':now(),'strict_results_sha256':digest(p/'results.json'),
       'review_code_sha256':digest(Path(__file__)),'changes':'Collapse internal whitespace only in issuer and share-class labels, matching the XML text reader. No security identifiers, numbers, position types or discretion values changed.',
       'samples':results,'passed':all(r['match_after_label_whitespace_normalization'] for r in results),
       'scope':'Three spot checks, not complete economic ownership qualification'})
    print(results)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
