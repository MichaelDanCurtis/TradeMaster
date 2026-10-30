"""Filing-date bounded annual SEC features; preserve missing/ambiguous facts."""
from datetime import date
from bisect import bisect_right
import math
import numpy as np

TAGS={'income':['NetIncomeLoss'],'ocf':['NetCashProvidedByUsedInOperatingActivities'],'capex':['PaymentsToAcquirePropertyPlantAndEquipment'],'revenue':['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'],'assets':['Assets'],'liabilities':['Liabilities'],'cash':['CashAndCashEquivalentsAtCarryingValue'],'eps':['EarningsPerShareDiluted']}
FEATURES=['income_assets','ocf_assets','fcf_assets','revenue_growth','ocf_growth','liabilities_assets','cash_assets','earnings_yield']

def compile_facts(payload):
    result={key:[] for key in TAGS};facts=payload.get('facts',{}).get('us-gaap',{})
    for metric,tags in TAGS.items():
        unit='USD/shares' if metric=='eps' else 'USD'
        for priority,tag in enumerate(tags):
            for item in facts.get(tag,{}).get('units',{}).get(unit,[]):
                try:
                    filed=date.fromisoformat(item['filed']);end=date.fromisoformat(item['end']);value=float(item['val']);start=date.fromisoformat(item['start']) if 'start' in item else None
                    if item.get('form') not in ['10-K','10-K/A','10-Q','10-Q/A'] or not math.isfinite(value) or end>filed:continue
                    if metric in ['assets','liabilities','cash']:
                        if start is not None:continue
                    elif start is None or not 330<=(end-start).days<=400:continue
                    result[metric].append({'filed':filed.isoformat(),'end':end.isoformat(),'start':start.isoformat() if start else None,'value':value,'accession':item.get('accn'),'tag':tag,'priority':priority})
                except (KeyError,ValueError,TypeError,OverflowError):continue
    return result

def latest(records,cutoff,end=None,start=None,minimum_end=None,maximum_end=None):
    valid=[r for r in records if r['filed']<cutoff and (end is None or r['end']==end) and (start is None or r['start']==start) and (minimum_end is None or r['end']>=minimum_end) and (maximum_end is None or r['end']<=maximum_end)]
    if not valid:return None
    best=max(valid,key=lambda r:(r['end'],r['filed'],-r['priority']));same=[r for r in valid if (r['end'],r['filed'],r['priority'])==(best['end'],best['filed'],best['priority'])]
    # Distinct annual durations/values on the same date are not guessed away.
    if len({(r['start'],r['value']) for r in same})!=1:return None
    return best

def snapshot(compiled,cutoff,price=None,split_unchanged=None):
    from datetime import timedelta
    minimum=(date.fromisoformat(cutoff)-timedelta(days=550)).isoformat();values=np.full(8,np.nan);evidence=[]
    def get(metric,**kwargs):
        record=latest(compiled.get(metric,[]),cutoff,minimum_end=minimum,**kwargs)
        if record is not None:evidence.append({'metric':metric,**record})
        return record
    def asset_ratio(numerator,index):
        n=get(numerator)
        if not n:return
        a=get('assets',end=n['end'])
        if a and a['value']>0:values[index]=n['value']/a['value']
    asset_ratio('income',0);asset_ratio('ocf',1)
    ocf=get('ocf')
    if ocf:
        capex=get('capex',end=ocf['end'],start=ocf['start']);assets=get('assets',end=ocf['end'])
        if capex and assets and assets['value']>0:values[2]=(ocf['value']-capex['value'])/assets['value']
    for metric,index in [('revenue',3),('ocf',4)]:
        now=get(metric)
        if not now:continue
        end=date.fromisoformat(now['end']);before=latest(compiled.get(metric,[]),cutoff,minimum_end=(end-timedelta(days=400)).isoformat(),maximum_end=(end-timedelta(days=330)).isoformat())
        if before and abs(before['value'])>0:
            values[index]=(now['value']-before['value'])/abs(before['value']);evidence.append({'metric':metric,**before})
    # Leverage and cash ratios use most recent available balance sheet, same end.
    assets=get('assets')
    if assets and assets['value']>0:
        for metric,index in [('liabilities',5),('cash',6)]:
            v=get(metric,end=assets['end'])
            if v:values[index]=v['value']/assets['value']
    eps=get('eps')
    if eps and price is not None and math.isfinite(price) and price>0 and split_unchanged is not None and split_unchanged(eps['end']):values[7]=eps['value']/price
    values[~np.isfinite(values)]=np.nan
    return values,evidence

def rank_observed(matrix):
    out=np.full_like(matrix,np.nan,dtype=float)
    from scripts.research.prediction_ranking import _rank_columns
    for j in range(matrix.shape[1]):
        mask=np.isfinite(matrix[:,j])
        if mask.any():out[mask,j]=_rank_columns(matrix[mask,j,None])[:,0]
    return out
