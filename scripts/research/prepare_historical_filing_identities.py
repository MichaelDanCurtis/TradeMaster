"""Cross-reference dated public issuer rows without reading any return data."""
import argparse,csv
from pathlib import Path
from scripts.research.event_research_pilot import read,write_new,digest,now


def covers(row, day):
    return max(row['date_added'].rstrip('*'),row['created_at'])<=day<(row['date_removed'].rstrip('*') or '9999-12-31')


def build(universe, source):
    rows=list(csv.DictReader(source.open()));result={};conflicts=[]
    for symbol, inherited in universe['issuers'].items():
        days=[d['membership_asof'] for d in universe['decisions'] if symbol in d['members']]
        matching=[r for r in rows if r['symbol'].replace('.','-')==symbol.replace('.','-') and any(covers(r,d) for d in days)]
        ids={r['cik'] for r in matching if r['cik'].isdigit() and len(r['cik'])==10}
        if len(ids)!=1:
            result[symbol]={'cik':'UNVERIFIED:'+symbol,'rows':matching,'reason':'missing_or_ambiguous_dated_identifier'}
            continue
        cik=ids.pop()
        if str(inherited).isdigit() and inherited!=cik:
            raise ValueError('Existing numeric mapping conflicts: '+symbol)
        result[symbol]={'cik':cik,'rows':matching}
        for day in days:
            if not any(covers(r,day) for r in matching):conflicts.append({'symbol':symbol,'membership_asof':day})
    return {'created_at':now(),'candidates':result,'date_conflicts':conflicts,
            'source_sha256':digest(source),'source':str(source.resolve()),
            'scope':'Community history candidate identities, validated further against original SEC documents. Not an official security master; source merges some later field corrections.'}


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--universe',type=Path,required=True);ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();x=build(read(a.universe),a.source);write_new(a.output,x)
    print({'candidates':len(x['candidates']),'date_conflicts':len(x['date_conflicts'])})
