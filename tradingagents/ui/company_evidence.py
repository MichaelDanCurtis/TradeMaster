"""Dated, reproducible issuer evidence. No model, broker writes, or recommendations."""
from __future__ import annotations
import json
import math
import os
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
import httpx
from tradingagents.research.data.store import ArtifactStore

_LOCK = threading.Lock()
_TICKERS = None
_LAST = 0.0
METRICS = {'revenue_growth': 'revenueGrowthTTMYoy', 'net_margin': 'netProfitMarginTTM',
           'pe': 'peTTM', 'market_cap': 'marketCapitalization'}
TAGS = {'revenue': ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'],
        'operating_cash_flow': ['NetCashProvidedByUsedInOperatingActivities'],
        'capex': ['PaymentsToAcquirePropertyPlantAndEquipment'],
        'net_income': ['NetIncomeLoss'], 'assets': ['Assets'], 'liabilities': ['Liabilities'],
        'cash': ['CashAndCashEquivalentsAtCarryingValue']}

def finite(value):
    if isinstance(value, bool): return None
    try: return float(value) if math.isfinite(float(value)) else None
    except (ValueError, TypeError): return None

class CompanySources:
    def __init__(self, root=None):
        self.store = ArtifactStore(Path(root or os.environ.get('TRADEMASTER_COMPANY_ARTIFACTS', '.research-artifacts/company/objects')))

    def read(self, url, params=None):
        global _LAST
        with _LOCK:
            time.sleep(max(0, .25 - (time.monotonic() - _LAST)))
            _LAST = time.monotonic()
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            with client.stream('GET', url, params=params, headers={'User-Agent': 'TradeMasterResearch/1.0 personal research desktop', 'Accept': 'application/json'}) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 15000000: raise ValueError('Source exceeds evidence size limit')
        payload = json.loads(body)
        digest = self.store.put(bytes(body))
        return payload, {'url': url, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'sha256': digest}

    def filing(self, url, symbol):
        from bs4 import BeautifulSoup
        from urllib.parse import urlsplit, urljoin
        global _LAST
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname!='www.sec.gov' or not parsed.path.startswith('/Archives/edgar/data/'):
            raise ValueError('Only SEC archive documents are accepted')
        with _LOCK:
            time.sleep(max(0,.25-(time.monotonic()-_LAST)));_LAST=time.monotonic()
        with httpx.Client(timeout=15,follow_redirects=False) as client:
            with client.stream('GET',url,headers={'User-Agent':'TradeMasterResearch/1.0 personal research desktop'}) as response:
                response.raise_for_status();body=bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body)>12000000:raise ValueError('Filing exceeds evidence limit')
        digest=self.store.put(bytes(body));soup=BeautifulSoup(bytes(body),'html.parser')
        security=None
        for table in soup.find_all('table')[:25]:
            heading=table.get_text(' ',strip=True)
            if 'Trading Symbol' not in heading or symbol not in heading:continue
            for row in table.find_all('tr'):
                cells=[c.get_text(' ',strip=True) for c in row.find_all('td')]
                if symbol in cells:
                    security=next((c for c in cells if c and c!=symbol),None)
                    break
        exhibit=None
        for link in soup.find_all('a',href=True):
            href=link['href'];candidate=urljoin(url,href)
            if '99' in href and candidate.startswith(url.rsplit('/',1)[0]+'/') and urlsplit(candidate).path.endswith(('.htm','.html')):
                exhibit=candidate;break
        for tag in soup.find_all(['script','style','ix:header','ix:hidden']):tag.decompose()
        text=' '.join(soup.get_text(' ',strip=True).split())
        import re
        matches=list(re.finditer(r'(?i)\b(?:business outlook|financial outlook|(?:q[1-4]|full year|fiscal)[A-Za-z0-9 ,\-]{0,30} outlook)\b',text))
        if not matches:matches=list(re.finditer(r'(?i)\boutlook\b',text))
        at=matches[0].start() if matches else 0
        # Prefer an actual short heading over incidental outlook language in a webcast announcement.
        for node in soup.find_all(['h1','h2','h3','h4','strong','b','span','div']):
            heading=' '.join(node.get_text(' ',strip=True).split())
            if re.fullmatch(r'(?i)(?:(?:business|financial|q[1-4][ A-Za-z0-9-]{0,20}|full year[ A-Za-z0-9-]{0,20}) )?outlook',heading):
                candidate=text.find(heading)
                if candidate>=0:at=candidate;break
        excerpt=' '.join(text[at:at+1200].split()[:100])
        return {'url':url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'sha256':digest,'text':excerpt,
                'security_description':security,'exhibit_url':exhibit,'excerpt_scope':'Selected excerpt only; the full document was not semantically reviewed.'}

    def collect(self, symbol):
        global _TICKERS
        result = {'symbol': symbol, 'collected_at': datetime.now(timezone.utc).isoformat(), 'profile': {}, 'metrics': {},
                  'financials': {}, 'filings': [], 'sources': [], 'gaps': [], 'security_type': 'unverified'}
        token = os.environ.get('FINNHUB_API_KEY')
        for endpoint in ['profile2', 'metric']:
            try:
                if not token: raise ValueError('No news provider key')
                payload, source = self.read('https://finnhub.io/api/v1/stock/' + endpoint, {'symbol': symbol, 'metric': 'all', 'token': token})
                if endpoint == 'profile2':
                    if payload.get('ticker') != symbol or not payload.get('name'): raise ValueError('Issuer identity unavailable')
                    result['profile'] = {k: payload.get(k) for k in ['ticker', 'name', 'exchange', 'country', 'currency', 'finnhubIndustry', 'ipo']}
                else:
                    if payload.get('symbol') != symbol: raise ValueError('Metric identity mismatch')
                    result['metrics'] = {k: finite(payload.get('metric', {}).get(v)) for k, v in METRICS.items()}
                result['sources'].append(source)
            except Exception:
                result['gaps'].append(f'Finnhub {endpoint} unavailable or identity unverified.')
        try:
            if _TICKERS is None or time.monotonic() - _TICKERS[0] > 86400:
                payload, source = self.read('https://www.sec.gov/files/company_tickers.json')
                _TICKERS = (time.monotonic(), payload, source)
            matches = [v for v in _TICKERS[1].values() if v.get('ticker') == symbol]
            if len(matches) != 1: raise ValueError('No unique SEC issuer mapping')
            cik = int(matches[0]['cik_str'])
            result['sources'].append(_TICKERS[2])
            submissions, source = self.read(f'https://data.sec.gov/submissions/CIK{cik:010d}.json')
            if int(submissions['cik']) != cik: raise ValueError('SEC identity mismatch')
            result['sources'].append(source)
            result['sec_name'] = submissions.get('name')
            result['cik'] = cik
            result['sic_description'] = submissions.get('sicDescription')
            # SEC issuer mapping does not establish share class or instrument type.
            recent = submissions.get('filings', {}).get('recent', {})
            for i, form in enumerate(recent.get('form', [])):
                if form not in {'10-K','10-Q','8-K','20-F','6-K'}: continue
                try:
                    filed = date.fromisoformat(recent['filingDate'][i])
                    accession = recent['accessionNumber'][i]
                    document = recent['primaryDocument'][i]
                    import re
                    if filed > date.today() or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession) or not re.fullmatch(r'[\w.\-]+', document): continue
                    result['filings'].append({'form':form, 'filed':filed.isoformat(), 'accession':accession,
                        'description':recent.get('primaryDocDescription', [''] * len(recent['form']))[i],
                        'url':f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-", "")}/{document}'})
                except (ValueError, KeyError, IndexError): continue
                if len(result['filings']) >= 12: break
            facts, source = self.read(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json')
            if int(facts['cik']) != cik: raise ValueError('Financial issuer mismatch')
            result['sources'].append(source)
            result['financials'] = financial_facts(facts)
            annual=next((r for r in result['filings'] if r['form'] in {'10-Q','10-K'}),None)
            earnings=next((r for r in result['filings'] if r['form']=='8-K'),None)
            result['filing_excerpts']=[]
            for filing in [r for r in [annual,earnings] if r]:
                try:
                    extracted=self.filing(filing['url'],symbol)
                    result['sources'].append({k:extracted[k] for k in ['url','retrieved_at','sha256']})
                    result['filing_excerpts'].append({**extracted,'filed':filing['filed'],'form':filing['form']})
                    description=extracted['security_description']
                    if description:
                        result['security_description']=description
                        lower=description.casefold()
                        result['security_type']='warrant' if 'warrant' in lower else 'preferred_stock' if 'preferred' in lower else 'common_stock' if 'common stock' in lower else 'registered_security_other'
                    if filing['form']=='8-K' and extracted['exhibit_url']:
                        exhibit=self.filing(extracted['exhibit_url'],symbol)
                        result['sources'].append({k:exhibit[k] for k in ['url','retrieved_at','sha256']})
                        result['filing_excerpts'].append({**exhibit,'filed':filing['filed'],'form':'8-K exhibit'})
                except Exception:
                    result['gaps'].append('A filing document or exhibit could not be retrieved; its link remains available.')
        except Exception:
            result['gaps'].append('SEC coverage incomplete. Missing filings or financials are not evidence of absence.')
        result['gaps'] += ['Metrics are current provider estimates; underlying as-of dates may be unavailable.',
            'Security type is identified only when an exact symbol row is found on a filing cover. Fund look-through and complete guidance interpretation remain unverified.',
            'Annual financials use the latest filed values and can include restatements; they are not point-in-time backtest inputs.']
        return result

def financial_facts(payload):
    """Retain exact periods and source tags; never subtract mismatched cash-flow periods."""
    output = {}
    gaap = payload.get('facts', {}).get('us-gaap', {})
    for metric, tags in TAGS.items():
        choices = []
        for tag in tags:
            for row in gaap.get(tag, {}).get('units', {}).get('USD', []):
                try:
                    end, filed = date.fromisoformat(row['end']), date.fromisoformat(row['filed'])
                    start = date.fromisoformat(row['start']) if row.get('start') else None
                    if filed > date.today() or end > filed or row.get('form') not in {'10-K','10-K/A','20-F','20-F/A'}: continue
                    if metric not in {'assets','liabilities','cash'} and (not start or not 330 <= (end-start).days <= 380): continue
                    value = finite(row['val'])
                    if value is None: continue
                    choices.append({'value':value, 'unit':'USD', 'start':row.get('start'), 'end':row['end'], 'filed':row['filed'], 'accession':row.get('accn'), 'tag':tag})
                except (ValueError, KeyError, TypeError): continue
        if choices: output[metric] = max(choices, key=lambda r:(r['end'], r['filed'], -tags.index(r['tag'])))
    ocf, capex = output.get('operating_cash_flow'), output.get('capex')
    if ocf and capex and all(ocf[k] == capex[k] for k in ['start','end','filed','accession']) and capex['value'] >= 0:
        output['free_cash_flow'] = {**ocf, 'value':ocf['value']-capex['value'], 'tag':ocf['tag']+' minus '+capex['tag']}
    return output

def screen(snapshot, min_growth=10, min_margin=0, require_fcf=True):
    checks = [('Revenue growth TTM (%)', snapshot['metrics'].get('revenue_growth'), min_growth),
              ('Net margin TTM (%)', snapshot['metrics'].get('net_margin'), min_margin)]
    if require_fcf:
        fact=snapshot['financials'].get('free_cash_flow', {})
        value=fact.get('value')
        if fact.get('end') and (date.today()-date.fromisoformat(fact['end'])).days>550:value=None
        checks.append(('Annual free cash flow (USD; period end within 550 days)', value, 0))
    rows = [{'name':name,'value':value,'threshold':threshold,'state':'unknown' if value is None else 'pass' if value > threshold else 'fail'} for name,value,threshold in checks]
    state = 'fail' if any(r['state']=='fail' for r in rows) else 'unknown' if any(r['state']=='unknown' for r in rows) else 'pass'
    return {'state':state, 'checks':rows}
