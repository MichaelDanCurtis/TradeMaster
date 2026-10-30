import pytest
from tradingagents.research.historical_filings import instance_identity, choose_portfolio


def xml_context(cid, cik, end, dimension=''):
    return f'<context id="{cid}"><entity><identifier scheme="http://www.sec.gov/CIK">{cik}</identifier>{dimension}</entity><period><instant>{end}</instant></period></context>'


def test_external_instance_ignores_subsidiary_and_wrong_date():
    contexts = xml_context('parent','123','2018-12-31')+xml_context('sub','456','2018-12-31')+xml_context('later','123','2019-12-31')
    xml=f'''<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:dei="http://xbrl.sec.gov/dei/2018-01-31">{contexts}
    <dei:DocumentType contextRef="parent">10-K</dei:DocumentType>
    <dei:DocumentType contextRef="sub">10-Q</dei:DocumentType>
    <dei:DocumentType contextRef="later">WRONG</dei:DocumentType></xbrl>'''
    result=instance_identity(xml.encode(),{'cik':'123','reportDate':'2018-12-31'})
    assert result['dei']=={'documenttype':['10-K']}
    assert result['eligible_contexts']==['parent']


def test_external_identity_rejects_non_instance_and_dimensional_context():
    with pytest.raises(ValueError): instance_identity(b'<html/>',{'cik':'123','reportDate':'2018-12-31'})
    context=xml_context('dim','123','2018-12-31','<segment/>')
    xml=f'<xbrl xmlns="http://www.xbrl.org/2003/instance" xmlns:dei="http://xbrl.sec.gov/dei/2018-01-31">{context}<dei:DocumentType contextRef="dim">10-K</dei:DocumentType></xbrl>'
    assert instance_identity(xml.encode(),{'cik':'123','reportDate':'2018-12-31'})['dei']=={}


def pair(cik,score,filing='2019-02-01',entry='2019-02-06',accession='a'):
    return {'status':'structurally_validated','jaccard':score,'eligible_entry_date':entry,
            'new':{'cik':cik,'filingDate':filing,'acceptanceDateTime':filing+'T15:00:00+00:00','accessionNumber':accession}}


def test_future_filings_cannot_change_past_portfolio():
    members=['A','B','C'];issuers={'A':'1','B':'2','C':'3'}
    pairs=[pair('1',.9),pair('2',.8),pair('3',.7)]
    before=choose_portfolio(members,issuers,pairs,'2019-04-01')
    after=choose_portfolio(members,issuers,pairs+[pair('3',1,'2019-04-01','2019-04-04','future')],'2019-04-01')
    assert before==after
    assert before['selected']==['A']


def test_latest_score_is_used_even_when_older_score_would_win():
    pairs=[pair('1',1),pair('1',.1,'2019-03-01','2019-03-06','b'),pair('2',.8),pair('3',.7)]
    assert choose_portfolio(['A','B','C'],{'A':'1','B':'2','C':'3'},pairs,'2019-04-01')['selected']==['B']


def test_unmapped_stale_and_duplicate_issuers_remain_in_coverage():
    r=choose_portfolio(['A','AA','B','C'],{'A':'1','AA':'1','B':'UNKNOWN','C':'3'},
                       [pair('1',.8),pair('3',.9,'2018-01-01','2018-01-04')],'2019-04-01')
    assert r['selected']==['A']
    assert [x['state'] for x in r['coverage']]==['eligible','duplicate_issuer_share_class','unmapped_historical_issuer','no_qualified_fresh_pair']


def test_empty_and_ties_are_deterministic():
    assert choose_portfolio(['A'],{'A':'1'},[],'2019-04-01')['selected']==[]
    r=choose_portfolio(['C','B','A','D'],{'A':'1','B':'2','C':'3','D':'4'},
                       [pair(str(i),.8) for i in [4,2,3,1]],'2019-04-01')
    assert r['selected']==['A','B']


def test_old_html_comments_do_not_break_identity_parser():
    from tradingagents.research.historical_filings import historical_inline_identity
    raw=b'<html><!-- legacy issuer comment --><body><p>Old filing</p></body></html>'
    assert historical_inline_identity(raw,{'cik':'123','reportDate':'2018-12-31'})['dei']=={}


def test_unqualified_newer_pair_cannot_displace_valid_available_evidence():
    old=pair('1',.8)
    bad=pair('1',1,'2019-03-01','2019-03-06','invalid')
    bad['status']='unqualified'
    result=choose_portfolio(['A'],{'A':'1'},[old,bad],'2019-04-01')
    assert result['eligible'][0]['accession']=='a'
