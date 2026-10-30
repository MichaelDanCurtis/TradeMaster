import json
from dataclasses import replace
from datetime import timedelta
import pytest
from tradingagents.research.contracts import content_hash,canonical_json
from tradingagents.research.evidence.extraction import Completion
from tradingagents.research.evidence.provider import ProviderBinding
from tradingagents.ui.db import create_session_factory,init_db
from tradingagents.ui.explorer_briefs import BriefService,BriefRequest,ExplorerBriefRecord,now_utc
from tradingagents.ui.thesis_challenge import challenge_packet,validate_challenge

BINDING=ProviderBinding('codex-test','codex-app-server','test-model',None,'a'*64,None,False)
def parent():
    claim={'text':'Revenue increased','kind':'observation','citations':[{'source_id':'filing','quote':'revenue increased'}]}
    packet={'sources':[{'source_id':'filing','text':'The filing says revenue increased but cash flow fell.','kind':'filing_excerpt'}],'scope':'Test evidence','gaps':[]}
    return ExplorerBriefRecord(symbol='NVDA',idempotency_key='original_brief_0001',request_hash='b'*64,provider_config_hash='a'*64,provider_id='codex-test',model_id='test-model',state='completed',deadline_at=now_utc()+timedelta(seconds=180),packet=packet,packet_hash=content_hash(packet),receipt={'proposal':{'overview':claim,'catalysts':[],'bull_case':[claim],'bear_case':[],'rejection_tests':['Check cash flow'],'gaps':['Valuation unknown']}})
def proposal():
    return {'summary':'Check the cash-flow implication','assessments':[{'claim_id':key,'verdict':'tension','reasoning':'Higher revenue does not establish higher cash flow.','citations':[{'source_id':'filing','quote':'cash flow fell'}],'evidence_to_change_assessment':'Comparable cash-flow statement'} for key in ['overview_0','bull_case_0']], 'falsification_tests':[{'claim_id':'bull_case_0','observation_required':'Verify operating cash flow in the filing','consequence':'Revise the cash generation assumption if it declined'}], 'missing_evidence':['Valuation'],'limitations':['Same model and source packet']}
def completion(p=None,**kwargs):
    return Completion(text=canonical_json(p or proposal()),provider_id=BINDING.provider_id,model_id=BINDING.model_id,input_tokens=100,output_tokens=100,**kwargs)

def test_packet_freezes_original_claims_and_sources():
    original=parent();packet=challenge_packet(original)
    assert packet['parent_packet_hash']==original.packet_hash
    assert packet['parent_receipt_hash']==content_hash(original.receipt)
    assert {c['claim_id'] for c in packet['target_claims']}=={'overview_0','bull_case_0'}
    packet['sources'][0]['text']='mutated'
    assert 'cash flow fell' in original.packet['sources'][0]['text']
    original.packet['sources'][0]['text']='tampered'
    with pytest.raises(ValueError,match='fingerprint'):challenge_packet(original)

def test_complete_claim_coverage_and_no_invented_evidence():
    packet=challenge_packet(parent())
    assert validate_challenge(completion(),packet,BINDING)['proposal']
    for mode in ['missing','duplicate','invented','uncited','bad_test']:
        p=proposal()
        if mode=='missing':p['assessments'].pop()
        if mode=='duplicate':p['assessments'][1]['claim_id']='overview_0'
        if mode=='invented':p['assessments'][0]['citations'][0]['source_id']='fake'
        if mode=='uncited':p['assessments'][0]['citations']=[]
        if mode=='bad_test':p['falsification_tests'][0]['claim_id']='fake'
        assert validate_challenge(completion(p),packet,BINDING)['proposal'] is None,mode

def test_missing_support_does_not_require_invented_citations_but_still_checks_provider():
    p=proposal()
    for a in p['assessments']:a.update(verdict='unsubstantiated',citations=[])
    packet=challenge_packet(parent())
    assert validate_challenge(completion(p),packet,BINDING)['proposal']
    assert validate_challenge(completion(p,tool_calls=True),packet,BINDING)['proposal'] is None
    assert validate_challenge(completion(p),packet,replace(BINDING,model_id='foreign'))['proposal'] is None

def test_quote_budget_applies_to_all_assessments():
    packet=challenge_packet(parent());packet['sources'][0]['text']=' '.join(f'word{i}' for i in range(40))
    p=proposal()
    p['assessments'][0]['citations'][0]['quote']=' '.join(f'word{i}' for i in range(15))
    p['assessments'][1]['citations'][0]['quote']=' '.join(f'word{i}' for i in range(15,30))
    assert validate_challenge(completion(p),packet,BINDING)['proposal'] is None

def test_challenge_is_idempotent_separate_and_shares_active_slot(tmp_path,monkeypatch):
    _,sessions=create_session_factory(f'sqlite:///{tmp_path}/test.db');init_db(sessions.kw['bind'])
    service=BriefService(sessions,lambda:pytest.fail('Challenge must not refresh market evidence'))
    monkeypatch.setattr(service,'binding',lambda:BINDING)
    original=parent()
    with sessions() as session:session.add(original);session.commit()
    request=BriefRequest(symbol='NVDA',idempotency_key='challenge_request_0001',provider_config_hash='a'*64,challenge_brief_id=original.brief_id)
    row,fresh=service.reserve(request)
    assert fresh and row.packet['parent_brief_id']==original.brief_id
    assert service.reserve(request)[1] is False
    assert [b.brief_id for b in service.history()]==[original.brief_id]
    assert [b.brief_id for b in service.history(purpose='challenge')]==[row.brief_id]
    with pytest.raises(ValueError,match='already running'):
        service.reserve(BriefRequest(symbol='NVDA',idempotency_key='new_original_00001',provider_config_hash='a'*64))
    with pytest.raises(ValueError,match='different inputs'):
        service.reserve(request.model_copy(update={'challenge_brief_id':None}))
    with pytest.raises(ValueError,match='does not match'):
        service.reserve(request.model_copy(update={'symbol':'MSFT','idempotency_key':'challenge_request_0002'}))

def test_original_request_hash_remains_backward_compatible(tmp_path,monkeypatch):
    _,sessions=create_session_factory(f'sqlite:///{tmp_path}/legacy.db');init_db(sessions.kw['bind'])
    service=BriefService(sessions,None);monkeypatch.setattr(service,'binding',lambda:BINDING)
    req=BriefRequest(symbol='NVDA',idempotency_key='legacy_request_0001',provider_config_hash='a'*64)
    row,_=service.reserve(req)
    assert row.request_hash==content_hash({'symbol':'NVDA','idempotency_key':'legacy_request_0001','provider_config_hash':'a'*64,'attachment_ids':[]})
