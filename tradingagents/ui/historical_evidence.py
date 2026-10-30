"""Historical filing packets from original inline XBRL, not current aggregates.

An explicit next-day availability rule excludes same-day filings. Current ticker
metadata is only a discovery hint, verified against a historical filing's cover.
"""
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
import re
from bs4 import BeautifulSoup
from tradingagents.ui.company_evidence import CompanySources,TAGS
from tradingagents.research.contracts import content_hash,canonical_json

FORMS={'10-K','10-K/A','10-Q','10-Q/A','8-K','8-K/A'}
RULE='Only filings with an SEC filing date strictly before the decision date are included. Same-day filings are excluded; no intraday availability is inferred.'

def localname(node):return (node.name or '').split(':')[-1].lower()
def descendants(node,name):return node.find_all(lambda t:localname(t)==name)
def one_text(node,name):
    found=descendants(node,name)
    return found[0].get_text('',strip=True) if len(found)==1 else None


def filing_rows(columns,cutoff,cik):
    """Filter before returning metadata so future titles/dates cannot enter a packet."""
    rows=[]
    for i,form in enumerate(columns.get('form',[])):
        if form not in FORMS:continue
        try:
            filed=date.fromisoformat(columns['filingDate'][i]);accession=columns['accessionNumber'][i];document=columns['primaryDocument'][i]
            if not cutoff-timedelta(days=5*366)<=filed<cutoff:continue
            if not re.fullmatch(r'\d{10}-\d{2}-\d{6}',accession) or not re.fullmatch(r'[A-Za-z0-9_.-]+',document):continue
            rows.append({'form':form,'filed':filed.isoformat(),'accession':accession,
                'available_from':(filed+timedelta(days=1)).isoformat(),
                'url':f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-","")}/{document}'})
        except (IndexError,KeyError,ValueError,TypeError):continue
    return rows


def number_value(node):
    """Bounded supported transformations; no guessing on unsupported formats."""
    if node.get('xsi:nil','').lower()=='true':raise ValueError('nil')
    fmt=node.get('format','').split(':')[-1].lower()
    if fmt not in {'','numdotdecimal','num-dot-decimal','numcommadot','zerodash','zero-dash','fixed-zero'}:
        raise ValueError('unsupported transformation')
    value=node.get_text('',strip=True).replace('\xa0','').replace(' ','').replace(',','')
    if fmt in {'zerodash','zero-dash','fixed-zero'}:
        if value not in {'','-','—','–','0'}:raise ValueError('invalid zero transformation')
        value='0'
    # Parenthetical presentation is not inferred; inline sign is authoritative.
    if not re.fullmatch(r'\d+(?:\.\d+)?',value):raise ValueError('unsupported numeric text')
    scale=int(node.get('scale','0'));sign=node.get('sign','')
    if not -12<=scale<=12 or sign not in {'','-'}:raise ValueError('invalid numeric attributes')
    result=Decimal(value)*(Decimal(10)**scale)*(-1 if sign=='-' else 1)
    if not result.is_finite():raise ValueError('nonfinite')
    return result


def extract_inline_facts(raw,cik,symbol,filing):
    soup=BeautifulSoup(raw,'html.parser');contexts={};units={};gaps=[]
    # Confirm the symbol within original cover data, rather than today's ticker map.
    symbols={n.get_text(' ',strip=True) for n in soup.find_all(lambda t:localname(t)=='nonnumeric') if n.get('name','').lower()=='dei:tradingsymbol'}
    ciks={n.get_text('',strip=True) for n in soup.find_all(lambda t:localname(t)=='nonnumeric') if n.get('name','').lower()=='dei:entitycentralindexkey'}
    identity=symbol in symbols and any(v.isdigit() and int(v)==cik for v in ciks)
    for context in soup.find_all(lambda t:localname(t)=='context'):
        ident=context.get('id')
        if not ident or ident in contexts:continue
        if descendants(context,'explicitmember') or descendants(context,'typedmember') or descendants(context,'segment') or descendants(context,'scenario'):continue
        entity=one_text(context,'identifier')
        if not entity or not entity.isdigit() or int(entity)!=cik:continue
        instant=one_text(context,'instant');start=one_text(context,'startdate');end=one_text(context,'enddate')
        try:
            end=date.fromisoformat(instant or end);start=date.fromisoformat(start) if start and not instant else None
            if end>date.fromisoformat(filing['filed']) or start and start>end:continue
            contexts[ident]={'start':start.isoformat() if start else None,'end':end.isoformat()}
        except (ValueError,TypeError):continue
    for unit in soup.find_all(lambda t:localname(t)=='unit'):
        measures=descendants(unit,'measure')
        if len(measures)==1 and measures[0].get_text('',strip=True).lower()=='iso4217:usd' and not descendants(unit,'divide'):
            units[unit.get('id')]='USD'
    supported={f'us-gaap:{tag}'.lower():(metric,tag) for metric,tags in TAGS.items() for tag in tags}
    values={};skipped=0
    for node in soup.find_all(lambda t:localname(t)=='nonfraction'):
        entry=supported.get(node.get('name','').lower());context=contexts.get(node.get('contextref'));unit=units.get(node.get('unitref'))
        if not entry or not context or unit!='USD':continue
        metric,tag=entry
        if metric in {'assets','liabilities','cash'} and context['start'] is not None:continue
        if metric not in {'assets','liabilities','cash'}:
            if not context['start']:continue
            days=(date.fromisoformat(context['end'])-date.fromisoformat(context['start'])).days
            if not 60<=days<=380:continue
        try:value=number_value(node)
        except (ValueError,InvalidOperation,TypeError):skipped+=1;continue
        key=(metric,context['start'],context['end'],tag)
        values.setdefault(key,set()).add(value)
    facts=[]
    for (metric,start,end,tag),candidates in sorted(values.items(),key=str):
        if len(candidates)!=1:
            gaps.append(f'Conflicting {metric} values for {start}–{end} were excluded.');continue
        facts.append({'metric':metric,'tag':tag,'value':str(next(iter(candidates))),'unit':'USD','start':start,'end':end,
            'accession':filing['accession'],'filed':filing['filed'],'available_from':filing['available_from'],'form':filing['form'],'source_url':filing['url']})
    if skipped:gaps.append(f'{skipped} targeted numeric tags had unsupported formatting and were excluded.')
    if not facts:gaps.append('No supported whole-entity USD facts could be extracted from this original filing.')
    return {'identity_verified':identity,'facts':facts,'gaps':gaps}


def exhibit_links(raw,url):
    """Use the exhibit table labels, not an assumed filename convention."""
    from urllib.parse import urljoin,urlsplit
    soup=BeautifulSoup(raw,'html.parser');links=[];parent=url.rsplit('/',1)[0]+'/'
    for row in soup.find_all('tr'):
        cells=row.find_all('td',recursive=False)
        if not any(re.fullmatch(r'99\.\d+',c.get_text(' ',strip=True).strip()) for c in cells):continue
        for link in row.find_all('a',href=True):
            candidate=urljoin(url,link['href']);parsed=urlsplit(candidate)
            if (candidate.startswith(parent) and parsed.scheme=='https' and parsed.hostname=='www.sec.gov'
                and not parsed.query and not parsed.fragment and parsed.path.endswith(('.htm','.html')) and candidate not in links):
                links.append(candidate)
    return links[:2]


def select_facts(facts):
    """Keep latest reported period and comparable prior-year period, with provenance."""
    selected=[]
    for metric,tags in TAGS.items():
        choices=[f for f in facts if f['metric']==metric]
        if not choices:continue
        # End first, then latest filing and cumulative period. Never combine unlike periods.
        rank=lambda f:(f['end'],f['filed'],(date.fromisoformat(f['end'])-date.fromisoformat(f['start'])).days if f['start'] else 0,-tags.index(f['tag']))
        current=max(choices,key=rank);selected.append({**current,'period_role':'latest'})
        prior=[]
        for f in choices:
            distance=(date.fromisoformat(current['end'])-date.fromisoformat(f['end'])).days
            duration=(date.fromisoformat(f['end'])-date.fromisoformat(f['start'])).days if f['start'] else None
            current_duration=(date.fromisoformat(current['end'])-date.fromisoformat(current['start'])).days if current['start'] else None
            if 330<=distance<=400 and ((duration is None and current_duration is None) or duration is not None and current_duration is not None and abs(duration-current_duration)<=8):prior.append(f)
        if prior:selected.append({**max(prior,key=rank),'period_role':'prior_year_comparable'})
    ocfs=[f for f in selected if f['metric']=='operating_cash_flow']
    for ocf in ocfs:
        cap=next((f for f in selected if f['metric']=='capex' and all(f[k]==ocf[k] for k in ['start','end','accession','filed','period_role'])),None)
        if cap and Decimal(cap['value'])>=0:
            selected.append({**ocf,'metric':'free_cash_flow','value':str(Decimal(ocf['value'])-Decimal(cap['value'])),'tag':ocf['tag']+' minus '+cap['tag'],'derivation':'Operating cash flow minus capital expenditure from the same filing and period.'})
    return selected


class HistoricalEvidence:
    def __init__(self,sources=None):self.sources=sources or CompanySources()

    def collect(self,symbol,cutoff):
        if not isinstance(cutoff,date):cutoff=date.fromisoformat(cutoff)
        sources=[];receipts=[];gaps=[]
        tickers,receipt=self.sources.read('https://www.sec.gov/files/company_tickers.json');receipts.append(receipt)
        matches=[v for v in tickers.values() if v.get('ticker')==symbol]
        if len(matches)!=1:raise ValueError('No unique issuer discovery mapping')
        cik=int(matches[0]['cik_str'])
        metadata,receipt=self.sources.read(f'https://data.sec.gov/submissions/CIK{cik:010d}.json');receipts.append(receipt)
        if int(metadata.get('cik',-1))!=cik:raise ValueError('Issuer history mismatch')
        rows=filing_rows(metadata.get('filings',{}).get('recent',{}),cutoff,cik)
        pages=[]
        for page in metadata.get('filings',{}).get('files',[]):
            try:
                if date.fromisoformat(page['filingFrom'])<cutoff and date.fromisoformat(page['filingTo'])>=cutoff-timedelta(days=5*366):pages.append(page)
            except (KeyError,ValueError):gaps.append('A historical filing index has unverifiable date coverage.')
        if len(pages)>10:gaps.append('Historical index coverage exceeds ten pages; remaining pages were not read.')
        for page in pages[:10]:
            if not re.fullmatch(rf'CIK{cik:010d}-submissions-\d+\.json',page.get('name','')):
                gaps.append('An unrecognized historical index filename was excluded.');continue
            try:
                data,receipt=self.sources.read('https://data.sec.gov/submissions/'+page['name']);receipts.append(receipt)
                rows.extend(filing_rows(data,cutoff,cik))
            except Exception:gaps.append('A historical index page could not be read; coverage is incomplete.')
        by_accession={r['accession']:r for r in rows};rows=sorted(by_accession.values(),key=lambda r:(r['filed'],r['accession']),reverse=True)
        chosen=[]
        for family in [{'10-K','10-K/A'},{'10-Q','10-Q/A'},{'8-K','8-K/A'}]:
            candidates=[r for r in rows if r['form'] in family]
            # Include the original if the latest amendment omits financial statements.
            chosen.extend(candidates[:2] if candidates and candidates[0]['form'].endswith('/A') else candidates[:1])
        facts=[];identity=False;documents=[]
        for filing in chosen:
            try:
                document=self.sources.filing(filing['url'],symbol)
                raw=self.sources.store.get(document['sha256'])
                parsed=extract_inline_facts(raw,cik,symbol,filing)
                identity=identity or parsed['identity_verified']
                facts.extend(parsed['facts']);gaps.extend(parsed['gaps'] if filing['form'].startswith(('10-K','10-Q')) else [])
                documents.append({**filing,'sha256':document['sha256'],'retrieved_at':document['retrieved_at'],'identity_verified':parsed['identity_verified']})
                receipts.append({k:document[k] for k in ['url','sha256','retrieved_at']})
                sources.append({'source_id':f'filing_{len(sources)}','title':f"{filing['form']} filed {filing['filed']} — selected excerpt",'publisher':'SEC issuer filing',
                    'kind':'filing_excerpt','published_at':filing['filed'],'available_from':filing['available_from'],'retrieved_at':document['retrieved_at'],
                    'url':filing['url'],'text':document['text'],'original_sha256':document['sha256'],'accession':filing['accession']})
                links = exhibit_links(raw, filing['url']) if filing['form'].startswith('8-K') else []
                if filing['form'].startswith('8-K') and not links:
                    gaps.append('No supported exhibit-table links were found in the selected 8-K.')
                for exhibit_url in links:
                    exhibit=self.sources.filing(exhibit_url,symbol)
                    receipts.append({k:exhibit[k] for k in ['url','sha256','retrieved_at']})
                    documents.append({**filing,'form':filing['form']+' exhibit','url':exhibit['url'],'sha256':exhibit['sha256'],'retrieved_at':exhibit['retrieved_at'],'identity_verified':False})
                    sources.append({'source_id':f'filing_{len(sources)}','title':f"8-K exhibit filed {filing['filed']} — selected excerpt",'publisher':'SEC issuer filing','kind':'filing_excerpt',
                        'published_at':filing['filed'],'available_from':filing['available_from'],'retrieved_at':exhibit['retrieved_at'],'url':exhibit['url'],'text':exhibit['text'],
                        'original_sha256':exhibit['sha256'],'accession':filing['accession']})
            except Exception:gaps.append(f"Selected {filing['form']} filed {filing['filed']} could not be fully verified or read.")
        if not identity:raise ValueError('Historical ticker and CIK were not verified in an original filing')
        selected=select_facts(facts)
        for accession in sorted({f['accession'] for f in selected}):
            group=[f for f in selected if f['accession']==accession];document=next(d for d in documents if d['accession']==accession)
            sources.append({'source_id':f'facts_{len(sources)}','title':f"Original {document['form']} numeric facts, filed {document['filed']}",'publisher':'SEC issuer inline XBRL',
                'kind':'historical_facts','published_at':document['filed'],'available_from':document['available_from'],'retrieved_at':document['retrieved_at'],'url':document['url'],
                'text':canonical_json({'symbol':symbol,'cik':cik,'facts':group}),'original_sha256':document['sha256'],'accession':accession})
        if not selected:gaps.append('Numeric coverage unavailable; the historical packet contains only filing excerpts.')
        missing = set(TAGS)-{f['metric'] for f in selected}
        if missing:gaps.append('No supported original-document values for: '+', '.join(sorted(missing))+'.')
        gaps+=['Same-day filings are excluded under the declared next-day rule.',
            'Original filing bytes were retrieved today. Their historical contents are reconstructed, not a contemporaneous capture.',
            'The current ticker map is only a discovery hint; an original filing confirms this ticker and CIK, not uninterrupted listing history or share-class continuity.',
            'Only selected filing excerpts and supported whole-entity USD tags are extracted. Unsupported tags, dimensions and number formats remain gaps.',
            'These facts retain their own fiscal periods and filing dates; no current TTM metrics or later restatements are substituted.']
        return {'symbol':symbol,'decision_date':cutoff.isoformat(),'collected_at':datetime.now(timezone.utc).isoformat(),'sources':sources,'gaps':gaps,'facts':selected,
            'scope':'Latest eligible annual, quarterly and current-report filing (and available amendment originals), using original documents and a five-year filing-index search.',
            'availability_rule':RULE,'identity':{'cik':cik,'symbol':symbol,'historical_document_verified':identity},'documents':documents,'source_receipts':receipts,
            'collector_code_hash':content_hash({'source':__import__('pathlib').Path(__file__).read_text()})}
