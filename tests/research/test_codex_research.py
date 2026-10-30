from collections import deque
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from tradingagents.research.contracts import ExtractionPolicy
from tradingagents.research.evidence import codex
from tradingagents.research.evidence.provider import ProviderBinding,ProviderExtractionClient,validate_billing


def policy(**updates):
    return ExtractionPolicy(max_calls=1,max_input_tokens=65536,max_output_tokens=8192,
        input_usd_per_million=0,output_usd_per_million=0,pricing_reference='Codex subscription allowance',
        billing_mode='codex_subscription',timeout_seconds=10,**updates)


def binding():
    return ProviderBinding('codex','codex-app-server','gpt-6-astra',None,'a'*64,None,False,'/test/codex','/test/home')


def event(method,**params): return {'method':method,'params':{'threadId':'thread','turnId':'turn',**params}}


@pytest.fixture
def transport(monkeypatch):
    state=SimpleNamespace(requests=[],closed=False,auth='chatgpt',models=[{'model':'gpt-6-astra'}],
        mcp={},actual_model='gpt-6-astra',events=[
            event('thread/tokenUsage/updated',tokenUsage={'total':{'inputTokens':500,'outputTokens':10}}),
            event('item/completed',item={'id':'reply','type':'agentMessage','phase':'final_answer','text':'{"status":"ok"}'}),
            event('turn/completed',turn={'id':'turn','status':'completed'})])
    class FakeServer:
        def __init__(self,*args,**kwargs):
            self.pending=deque();self.process=SimpleNamespace(poll=lambda:None)
        def request(self,method,params):
            state.requests.append((method,params))
            if method=='initialize':return {}
            if method=='account/read':return {'account':{'type':state.auth}}
            if method=='model/list':return {'data':state.models}
            if method=='config/read':return {'config':{'mcp_servers':state.mcp}}
            if method=='thread/start':return {'thread':{'id':'thread'},'model':state.actual_model,'modelProvider':'openai','activePermissionProfile':{'id':'trademaster_research'},'approvalPolicy':'never'}
            if method=='turn/start':self.pending.extend(state.events);return {'turn':{'id':'turn'}}
            raise AssertionError(method)
        def send(self,request):state.requests.append((request['method'],request.get('params')))
        def read(self):raise RuntimeError('Lost completion receipt')
        def close(self):state.closed=True
    monkeypatch.setattr(codex,'AppServer',FakeServer)
    return state


def complete():return codex.complete(binding(),policy(),system='No tools',user='{}',schema={'type':'object'})


def test_subscription_receipt_and_exact_single_turn(transport):
    receipt=complete()
    assert receipt.text=='{"status":"ok"}' and receipt.model_id=='gpt-6-astra'
    assert receipt.cost_usd==Decimal(0) and receipt.cost_basis=='subscription_usage'
    assert (receipt.input_tokens,receipt.output_tokens)==(500,10)
    calls=dict(transport.requests)
    assert calls['account/read']=={'refreshToken':False}
    assert calls['thread/start']['ephemeral'] and calls['thread/start']['environments']==[]
    assert calls['thread/start']['permissions']=='trademaster_research'
    assert calls['turn/start']['permissions']=='trademaster_research'
    assert calls['turn/start']['approvalPolicy']=='never'
    assert sum(m=='turn/start' for m,_ in transport.requests)==1 and transport.closed


@pytest.mark.parametrize('auth',['apiKey',None,'amazonBedrock'])
def test_no_fallback_to_other_authentication(transport,auth):
    transport.auth=auth
    with pytest.raises(ValueError,match='ChatGPT'):complete()
    assert not any(m=='turn/start' for m,_ in transport.requests) and transport.closed


def test_missing_model_and_enabled_mcp_stop_before_sampling(transport):
    transport.models=[]
    with pytest.raises(ValueError,match='Pinned model'):complete()
    transport.models=[{'model':'gpt-6-astra'}];transport.mcp={'broker':{'enabled':True}}
    with pytest.raises(ValueError,match='MCP'):complete()
    assert not any(m=='turn/start' for m,_ in transport.requests)


@pytest.mark.parametrize('bad,match',[
    (event('model/rerouted',toModel='different'),'rerouted'),
    (event('item/started',item={'id':'tool','type':'commandExecution'}),'forbidden'),
    (event('thread/tokenUsage/updated',tokenUsage={'total':{'inputTokens':500,'outputTokens':8193}}),'exceeded'),
    (event('turn/completed',turn={'id':'turn','status':'failed'}),'did not complete'),
])
def test_unacceptable_outcomes_interrupt_without_retry(transport,bad,match):
    transport.events.insert(0,bad)
    if match in {'forbidden','exceeded'}:
        assert any(match in error for error in complete().validation_errors)
    else:
        with pytest.raises((ValueError,RuntimeError),match=match):complete()
    assert sum(m=='turn/start' for m,_ in transport.requests)==1
    assert any(m=='turn/interrupt' for m,_ in transport.requests) and transport.closed


def test_usage_missing_and_foreign_thread_output_never_become_valid_evidence(transport):
    transport.events=transport.events[1:]
    transport.events.insert(0,{'method':'item/completed','params':{'threadId':'foreign','turnId':'turn','item':{'id':'foreign','type':'agentMessage','text':'wrong'}}})
    receipt=complete()
    assert receipt.text=='{"status":"ok"}'
    assert receipt.input_tokens is None and receipt.validation_errors


def test_subscription_contract_requires_explicit_review_and_zero_api_prices():
    p=policy()
    with pytest.raises(ValueError,match='API token charge'):
        ExtractionPolicy.model_validate({**p.model_dump(),'input_usd_per_million':1})
    with pytest.raises(ValueError,match='subscription'):
        validate_billing(binding(),p.model_copy(update={'billing_mode':'api_metered'}))
    with pytest.raises(ValueError,match='api metered'):
        validate_billing(ProviderBinding('api','openai','model',None,'a'*64,None,False),p)


def test_real_protocol_timeout_reaps_process_and_strips_broker_environment(tmp_path,monkeypatch):
    monkeypatch.setenv('ALPACA_SECRET_KEY','must-not-reach-codex')
    real=subprocess.Popen;seen={}
    def hung(args,**kwargs):
        seen.update(kwargs);seen['args']=args
        return real([sys.executable,'-c','import time;time.sleep(20)'],**kwargs)
    monkeypatch.setattr(codex.subprocess,'Popen',hung)
    server=codex.AppServer('/test/codex',str(tmp_path),str(tmp_path),.1)
    try:
        with pytest.raises(TimeoutError):server.request('initialize',{})
    finally:server.close()
    assert server.process.poll() is not None
    assert 'ALPACA_SECRET_KEY' not in seen['env'] and 'OPENAI_API_KEY' not in seen['env']
    assert 'features.hooks=false' in seen['args'] and 'features.apps=false' in seen['args']
    assert 'features.plugins=false' in seen['args'] and 'features.shell_tool=false' in seen['args']


def test_unsolicited_server_approval_is_rejected(tmp_path,monkeypatch):
    real=subprocess.Popen
    message=json.dumps({'id':22,'method':'item/commandExecution/requestApproval','params':{}})
    def fake(args,**kwargs):
        return real([sys.executable,'-c',f'import time;print({message!r},flush=True);time.sleep(20)'],**kwargs)
    monkeypatch.setattr(codex.subprocess,'Popen',fake)
    server=codex.AppServer('/test/codex',str(tmp_path),str(tmp_path),2)
    try:
        with pytest.raises(ValueError,match='forbidden tool or approval'):server.read()
    finally:server.close()
    assert server.process.poll() is not None


def test_strict_wire_schema_preserves_application_validation():
    from tradingagents.research.designer import schema_info
    original=schema_info()['schema']
    wire=codex.strict_schema(original)
    def inspect(node):
        if isinstance(node,dict):
            assert 'default' not in node and 'oneOf' not in node and 'discriminator' not in node
            if 'properties' in node:
                assert set(node['required'])==set(node['properties']) and node['additionalProperties'] is False
            for child in node.values():inspect(child)
        elif isinstance(node,list):
            for child in node:inspect(child)
    inspect(wire)
    # Conversion is a copy; frozen application prompt/schema hashes stay intact.
    assert original==schema_info()['schema']


def test_subscription_overrun_is_preserved_and_invalidates_design(transport):
    from tradingagents.research.designer import DesignInput,schema_info,validate_completion
    from tests.research.conftest import spec_payload
    transport.events.insert(0,event('thread/tokenUsage/updated',tokenUsage={'total':{'inputTokens':100,'outputTokens':9000}}))
    completion=complete()
    request=DesignInput(idempotency_key='limit',expected_revision=1,family_id='family',max_trials=3,
        compute_budget_usd=1,brief='Review',constraints=spec_payload(),provider_id='codex',model_id='gpt-6-astra',
        provider_config_hash='a'*64,prompt_hash=schema_info()['prompt_hash'],schema_hash=schema_info()['schema_hash'],policy=policy())
    receipt=validate_completion(completion,request)
    assert receipt.bound_exceeded and receipt.proposal is None
    assert receipt.output_tokens==9000 and receipt.cost_basis=='subscription_usage'


def test_images_use_only_temporary_local_paths_and_keep_tool_boundary(transport):
    data=b'\x89PNG\r\n\x1a\nfixture'
    result=codex.complete(binding(),policy(),system='No tools',user='Read supplied image',schema={'type':'object'},images=[('attachment_1_p1',data)])
    params=next(p for m,p in transport.requests if m=='turn/start')
    assert [p['type'] for p in params['input']]==['text','text','localImage']
    assert params['permissions']=='trademaster_research' and params['approvalPolicy']=='never'
    assert 'attachment_1_p1' in params['input'][1]['text']
    assert not Path(params['input'][2]['path']).exists()  # Deleted after the ephemeral call.
    assert result.model_id=='gpt-6-astra'


def test_images_reject_paths_bad_ids_and_unbounded_inputs(tmp_path):
    for inputs in [[('../secret',b'\x89PNG\r\n\x1a\n')],[('attachment_1_p1',b'not png')],[('attachment_1_p1',b'\x89PNG\r\n\x1a\n')]*5]:
        with pytest.raises(ValueError):codex.image_inputs(tmp_path,inputs)
