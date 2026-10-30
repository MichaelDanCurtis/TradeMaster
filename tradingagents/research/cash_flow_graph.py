"""Public-manager coholding proxy. No prices, returns, or broker execution."""
import re
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
import numpy as np


def day(value):
    return datetime.strptime(value, '%d-%b-%Y').date().isoformat()


def company_key(value):
    words=re.findall(r'[A-Z0-9]+',value.upper().replace('&',' AND '))
    aliases={'CORPORATION':'CORP','INCORPORATED':'INC','COMPANY':'CO','INTERNATIONAL':'INTL','TECHNOLOGIES':'TECH','SYSTEMS':'SYS','LABORATORIES':'LABS'}
    words=[aliases.get(w,w) for w in words]
    while words and words[-1] in {'INC','CORP','CO','LTD','PLC','AND'}:words.pop()
    return ''.join(words)


def common(row):
    return (row['SSHPRNAMTTYPE']=='SH' and not row['PUTCALL'].strip()
        and row['TITLEOFCLASS'].strip().upper() in {'COM','COM NEW','COMMON','COMMON STOCK','CL A','CLASS A','CL B','CLASS B','COM CL A','COM CL B','CAP STK CL A'})


def eligible_reports(submissions,covers,cutoff,max_age=180):
    by_manager=defaultdict(list)
    for acc,s in submissions.items():
        if day(s['FILING_DATE'])<=cutoff and s['SUBMISSIONTYPE'] in {'13F-HR','13F-HR/A'}:
            by_manager[s['CIK']].append((acc,s))
    chosen={};excluded=Counter()
    for cik,items in by_manager.items():
        period=max(day(s['PERIODOFREPORT']) for _,s in items)
        age=(datetime.fromisoformat(cutoff)-datetime.fromisoformat(period)).days
        latest=[(a,s) for a,s in items if day(s['PERIODOFREPORT'])==period]
        if age<0 or age>max_age:excluded['stale_or_future_report']+=1;continue
        if len(latest)!=1 or latest[0][1]['SUBMISSIONTYPE']!='13F-HR':excluded['amended_or_multiple_originals']+=1;continue
        acc,s=latest[0];cover=covers.get(acc,{})
        if cover.get('REPORTTYPE')!='13F HOLDINGS REPORT' or cover.get('ISAMENDMENT')=='Y' or cover.get('CONFDENIEDEXPIRED')=='Y':
            excluded['cover_or_confidentiality']+=1;continue
        chosen[acc]={'manager':cik,'filed':day(s['FILING_DATE']),'reported':period}
    return chosen,dict(excluded)


def build_graph(rows_by_manager,target_cusip,destinations,cash_per_share,*,target_key=None,destination_keys=None):
    """Require sole-discretion, unambiguous equity rows; never multiply duplicates."""
    managers=[];cash=[];aum=[];weights=[];exclusions=Counter();coverage=[]
    for manager,rows in sorted(rows_by_manager.items()):
        if any(r['INVESTMENTDISCRETION']!='SOLE' or r['OTHERMANAGER'].strip() for r in rows):
            exclusions['shared_or_other_manager']+=1;continue
        equity=[r for r in rows if common(r)]
        if len({r['CUSIP'] for r in equity})!=len(equity):exclusions['duplicate_common_cusip']+=1;continue
        try:
            values={r['CUSIP']:float(Decimal(r['VALUE'])*1000) for r in equity}
            shares={r['CUSIP']:float(Decimal(r['SSHPRNAMT'])) for r in equity}
        except Exception:exclusions['invalid_numeric']+=1;continue
        if any(not np.isfinite(x) or x<0 for x in [*values.values(),*shares.values()]):exclusions['invalid_numeric']+=1;continue
        if target_key is not None and any(r['CUSIP']==target_cusip and company_key(r['NAMEOFISSUER'])!=target_key for r in equity):
            exclusions['target_name_cusip_not_confirmed']+=1;continue
        eligible_values={r['CUSIP']:values[r['CUSIP']] for r in equity if destination_keys is None or company_key(r['NAMEOFISSUER'])==destination_keys.get(r['CUSIP'])}
        total=sum(values.values());other=total-values.get(target_cusip,0)
        if other<=0:exclusions['no_other_reported_equity']+=1;continue
        vector=[eligible_values.get(c,0)/other if c!=target_cusip else 0 for c in destinations]
        if sum(vector)<=0:exclusions['no_mapped_destinations']+=1;continue
        receipt=shares.get(target_cusip,0)*cash_per_share
        managers.append(manager);cash.append(receipt);aum.append(total);weights.append(vector)
        if receipt:coverage.append({'manager':manager,'hypothetical_cash_usd':receipt,'mapped_reinvestment_fraction':sum(vector)})
    return {'managers':managers,'cash':np.array(cash),'aum':np.array(aum),'weights':np.array(weights),
            'exclusions':dict(exclusions),'cash_owners':coverage}


def shuffled_cash(cash,aum,seed):
    """Shuffle cash across managers within reported-equity size quintiles."""
    rng=np.random.default_rng(seed);out=cash.copy()
    for group in np.array_split(np.argsort(aum,kind='stable'),5):out[group]=rng.permutation(cash[group])
    return out
