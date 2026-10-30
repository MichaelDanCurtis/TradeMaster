from datetime import date
from decimal import Decimal
from pathlib import Path
import pytest
from tradingagents.research.data.store import ArtifactStore
from tradingagents.ui.historical_evidence import filing_rows,extract_inline_facts,select_facts,HistoricalEvidence

FILING={'form':'10-Q','filed':'2023-05-25','available_from':'2023-05-26','accession':'0000000001-23-000001','url':'https://www.sec.gov/Archives/edgar/data/1/000000000123000001/report.htm'}
def html(extra='',symbol='NVDA',entity='1'):
    return f'''<html><body>
    <ix:nonnumeric name="dei:TradingSymbol">{symbol}</ix:nonnumeric><ix:nonnumeric name="dei:EntityCentralIndexKey">{entity}</ix:nonnumeric>
    <xbrli:context id="quarter"><xbrli:entity><xbrli:identifier>{entity}</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-03-31</xbrli:endDate></xbrli:period></xbrli:context>
    <xbrli:context id="segment"><xbrli:entity><xbrli:identifier>1</xbrli:identifier><xbrli:segment><xbrldi:explicitMember>US</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2023-01-01</xbrli:startDate><xbrli:endDate>2023-03-31</xbrli:endDate></xbrli:period></xbrli:context>
    <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit><xbrli:unit id="eur"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
    <ix:nonfraction name="us-gaap:Revenues" contextRef="quarter" unitRef="usd" scale="6" format="ixt:numdotdecimal">1,234</ix:nonfraction>
    <ix:nonfraction name="us-gaap:NetCashProvidedByUsedInOperatingActivities" contextRef="quarter" unitRef="usd" scale="6" format="ixt:numdotdecimal">200</ix:nonfraction>
    <ix:nonfraction name="us-gaap:PaymentsToAcquirePropertyPlantAndEquipment" contextRef="quarter" unitRef="usd" scale="6" format="ixt:numdotdecimal">50</ix:nonfraction>
    {extra}</body></html>'''.encode()

def test_original_inline_units_scale_context_and_identity():
    p=extract_inline_facts(html(),1,'NVDA',FILING)
    assert p['identity_verified']
    assert next(f for f in p['facts'] if f['metric']=='revenue')['value']=='1234000000'
    selected=select_facts(p['facts']);fcf=next(f for f in selected if f['metric']=='free_cash_flow')
    assert Decimal(fcf['value'])==150000000 and fcf['accession']==FILING['accession']
    assert not extract_inline_facts(html(symbol='OTHER'),1,'NVDA',FILING)['identity_verified']
    assert not extract_inline_facts(html(entity='2'),1,'NVDA',FILING)['facts']

def test_segments_other_currency_future_period_and_unsupported_formats_excluded():
    extra='''<ix:nonfraction name="us-gaap:Revenues" contextRef="segment" unitRef="usd">999999</ix:nonfraction>
    <ix:nonfraction name="us-gaap:Revenues" contextRef="quarter" unitRef="eur">888888</ix:nonfraction>
    <ix:nonfraction name="us-gaap:Revenues" contextRef="quarter" unitRef="usd" format="ixt:unknown">777777</ix:nonfraction>'''
    p=extract_inline_facts(html(extra),1,'NVDA',FILING)
    assert next(f for f in p['facts'] if f['metric']=='revenue')['value']=='1234000000'
    assert p['gaps']
    assert not extract_inline_facts(html().replace(b'2023-03-31',b'2024-03-31'),1,'NVDA',FILING)['facts']

def test_conflicting_duplicate_values_never_choose_silently():
    extra='<ix:nonfraction name="us-gaap:Revenues" contextRef="quarter" unitRef="usd" scale="6">999</ix:nonfraction>'
    p=extract_inline_facts(html(extra),1,'NVDA',FILING)
    assert not any(f['metric']=='revenue' for f in p['facts'])
    assert any('Conflicting' in gap for gap in p['gaps'])

def test_later_and_same_day_filings_excluded_before_metadata_return():
    columns={'form':['10-Q']*3,'filingDate':['2023-05-25','2023-06-01','2024-05-25'],
        'accessionNumber':['0000000001-23-000001','0000000001-23-000002','0000000001-24-000001'],'primaryDocument':['a.htm','b.htm','future.htm']}
    rows=filing_rows(columns,date(2023,6,1),1)
    assert len(rows)==1 and rows[0]['available_from']=='2023-05-26'
    assert 'future' not in str(rows)

def test_fcf_requires_same_filing_and_period():
    p=extract_inline_facts(html(),1,'NVDA',FILING)['facts']
    for f in p:
        if f['metric']=='capex':f['accession']='different'
    assert not any(f['metric']=='free_cash_flow' for f in select_facts(p))

def test_collector_uses_historical_page_and_originals_not_aggregate_facts(tmp_path):
    class Source:
        def __init__(self):self.store=ArtifactStore(tmp_path);self.urls=[]
        def read(self,url):
            self.urls.append(url)
            if url.endswith('company_tickers.json'):value={'0':{'ticker':'NVDA','cik_str':1,'title':'FUTURE NAME'}}
            elif url.endswith('CIK0000000001.json'):value={'cik':1,'name':'FUTURE NAME','filings':{'recent':{'form':[]},'files':[{'name':'CIK0000000001-submissions-001.json','filingFrom':'2020-01-01','filingTo':'2024-01-01'}]}}
            else:value={'form':['10-Q','10-Q'],'filingDate':['2023-05-25','2024-01-01'],'accessionNumber':['0000000001-23-000001','0000000001-24-000001'],'primaryDocument':['report.htm','future.htm']}
            return value,{'url':url,'retrieved_at':'2026-09-07T00:00:00Z','sha256':self.store.put_json(value)}
        def filing(self,url,symbol):
            assert url==FILING['url']
            return {'url':url,'retrieved_at':'2026-09-07T00:00:00Z','sha256':self.store.put(html()),'text':'Original filing excerpt','exhibit_url':None}
    source=Source();p=HistoricalEvidence(source).collect('NVDA',date(2023,6,1))
    assert p['identity']['historical_document_verified'] and p['facts']
    assert not any('companyfacts' in u for u in source.urls)
    assert 'FUTURE NAME' not in str(p) and 'future.htm' not in str(p)
    assert all(s['published_at']<'2023-06-01' for s in p['sources'])

def test_replay_requires_exact_completed_assessment_before_reveal(tmp_path,monkeypatch):
    from datetime import timedelta
    from fastapi import HTTPException,BackgroundTasks
    from tradingagents.ui.db import create_session_factory,init_db
    from tradingagents.ui.research_desk import Desk
    from tradingagents.ui.opportunity_lab import OpportunityLab,ReplayRequest,DecisionRequest
    from tradingagents.ui.historical_replay import prepare,assess,EvidenceRequest,AssessmentRequest
    from tradingagents.ui.explorer_briefs import BriefService,ExplorerBriefRecord
    from tradingagents.research.evidence.provider import ProviderBinding
    from tradingagents.research.contracts import content_hash
    _,sessions=create_session_factory(f'sqlite:///{tmp_path}/replay.db');init_db(sessions.kw['bind']);lab=OpportunityLab(Desk(sessions),lambda:(object(),{}),tmp_path/'replay-objects')
    days=[];day=date(2023,1,2)
    while len(days)<100:
        if day.weekday()<5:days.append(day.isoformat())
        day+=timedelta(days=1)
    data={'symbol':'NVDA','feed':'sip','observed_at':'2026-09-07T00:00:00Z','calendar':[{'date':d,'open':'09:30','close':'16:00'} for d in days],'bars':{'NVDA':{d:{'close':100+i,'volume':1} for i,d in enumerate(days)}},'receipts':[]}
    monkeypatch.setattr('tradingagents.ui.opportunity_lab.capture',lambda *a,**k:data)
    replay=lab.create_replay(ReplayRequest(symbol='NVDA',cutoff=days[65],horizon=2,evidence_mode='filings'))
    decision=DecisionRequest(expected_step=0,decision='watch',thesis='A test of historical evidence',invalidation='A later observation contradicts it')
    with pytest.raises(HTTPException):lab.advance(replay['id'],decision)
    packet={'symbol':'NVDA','decision_date':days[65],'sources':[{'source_id':'filing_1','text':'Revenue increased','published_at':'2023-02-01','kind':'filing_excerpt'}],'gaps':['Limited coverage'],'scope':'Historical test','source_receipts':[],'documents':[]}
    monkeypatch.setattr(HistoricalEvidence,'collect',lambda *a:packet.copy())
    view=prepare(lab,replay['id'],EvidenceRequest(expected_step=0));saved=view['historical_evidence']['packet']
    assert days[66] not in str(saved) and days[67] not in str(saved)
    assert '166' not in saved['sources'][-1]['text']
    binding=ProviderBinding('codex-test','codex-app-server','test-model',None,'a'*64,None,False)
    monkeypatch.setattr(BriefService,'binding',lambda self:binding)
    background=BackgroundTasks();request=AssessmentRequest(expected_step=0,provider_config_hash='a'*64,idempotency_key='historical_request_0001')
    view=assess(lab,replay['id'],request,background);identifier=view['historical_evidence']['brief_id']
    assert len(background.tasks)==1
    assert not BriefService(sessions,None).history()
    assert len(BriefService(sessions,None).history(purpose='historical'))==1
    with pytest.raises(HTTPException):lab.advance(replay['id'],decision)
    with sessions() as session:
        row=session.get(ExplorerBriefRecord,identifier);row.state='completed';row.receipt={'proposal':{'test':'completed fixture'},'validation_errors':[]};session.add(row);session.commit()
    advanced=lab.advance(replay['id'],decision)
    assert advanced['step']==1 and advanced['visible_through']==days[66] and days[67] not in str(advanced['bars'])
    assert advanced['decisions'][0]['historical_assessment']['brief_id']==identifier
    assert advanced['historical_evidence'] is None
    with pytest.raises(HTTPException):lab.advance(replay['id'],decision.model_copy(update={'expected_step':1}))

def test_exhibit_table_resolves_real_names_and_rejects_external_or_traversal():
    from tradingagents.ui.historical_evidence import exhibit_links
    raw=b'''<table><tr><td>99.1</td><td><a href="q1fy24pr.htm">Press release</a></td></tr>
    <tr><td>99.2</td><td><a href="https://evil.example/pr.htm">External</a><a href="../future/pr.htm">Other filing</a><a href="q1fy24cfo.htm">CFO commentary</a></td></tr></table>'''
    assert exhibit_links(raw,FILING['url'])==[FILING['url'].rsplit('/',1)[0]+'/q1fy24pr.htm',FILING['url'].rsplit('/',1)[0]+'/q1fy24cfo.htm']
