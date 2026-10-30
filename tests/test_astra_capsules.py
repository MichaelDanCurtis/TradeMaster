"""Causality and contract checks for historical Astra decisions."""
import copy,json,math
from pathlib import Path
import pytest
from scripts.research.prepare_astra_capsules import build_packet
from scripts.research.evaluate_astra_capsules import validate,rows_for,sha

def fixture_panel():
    return {'dates':[f'session-{i}' for i in range(280)],'symbols':['A','B','C','D','E','F'],
      'series':{s:{'open':[100+i*(j+1)/100 for i in range(280)],'close':[100+i*(j+1)/100 for i in range(280)],'volume':[1000+i for i in range(280)]} for j,s in enumerate(['A','B','C','D','E','F','SPY'])}}

def test_packet_cannot_observe_future():
    p=fixture_panel();q=copy.deepcopy(p)
    for series in q['series'].values():
        for field in ['close','volume','open']:series[field][253:]=[None]*27
    assert build_packet(p,252,{'A','B','C'},'blind-test')==build_packet(q,252,{'A','B','C'},'blind-test')

def test_current_bad_history_excludes_only_affected_security():
    p=fixture_panel();p['series']['A']['volume'][250]=0
    packet,mapping=build_packet(p,252,{'A','B','C'},'blind-test')
    assert 'A' not in mapping.values()
    assert packet['required_selections']=={'diverse100':1,'sp500':2}

def test_named_and_blinded_features_match():
    import csv,io
    p=fixture_panel();blind,bmap=build_packet(p,252,{'A','B','C'},'blind-test');named,nmap=build_packet(p,252,{'A','B','C'},'named-test',True)
    def keyed(packet,mapping):
        return {mapping[r['id']]:{k:v for k,v in r.items() if k!='id'} for r in csv.DictReader(io.StringIO(packet['evidence_csv']))}
    assert keyed(blind,bmap)==keyed(named,nmap)
    assert 'session-252' not in json.dumps(blind)

def setup_contract(tmp_path):
    p=fixture_panel();packet,mapping=build_packet(p,252,{'A','B','C'},'blind-test')
    (tmp_path/'packets').mkdir();(tmp_path/'decisions').mkdir();path=tmp_path/'packets/blind-test.json';path.write_text(json.dumps(packet));inverse={s:i for i,s in mapping.items()}
    d={'case_id':'blind-test','diverse100':{'selected_ids':[inverse['A']],'rationale':'past','confidence':'low'},'sp500':{'selected_ids':[inverse['A'],inverse['F']],'rationale':'past','confidence':'low'},'method_summary':'rule','hindsight_disclosure':'none noticed','evidence_boundary_attestation':'packet only','limitations':['limited evidence']}
    (tmp_path/'decisions/blind-test.json').write_text(json.dumps(d));case={'case_id':'blind-test','packet_sha256':sha(path),'id_to_symbol':mapping,'origin_index':252,'entry_index':253,'exit_index':274,'date':'session-252','truncated':False}
    return p,d,case,inverse

def test_invalid_selection_is_rejected(tmp_path):
    p,d,c,inv=setup_contract(tmp_path);assert validate(tmp_path,c)==d
    d['diverse100']['selected_ids']=[inv['F']];(tmp_path/'decisions/blind-test.json').write_text(json.dumps(d))
    with pytest.raises(AssertionError):validate(tmp_path,c)

def test_duplicate_selection_is_rejected(tmp_path):
    p,d,c,inv=setup_contract(tmp_path);d['sp500']['selected_ids']=[inv['A'],inv['A']];(tmp_path/'decisions/blind-test.json').write_text(json.dumps(d))
    with pytest.raises(AssertionError):validate(tmp_path,c)

def test_translation_preserves_exact_choices(tmp_path):
    p,d,c,inv=setup_contract(tmp_path);rows=rows_for(p,[c],{'blind-test':d},'sp500');r=rows[0]
    assert {s for s,v in zip(r['eligible_symbols'],r['scores']['astra']) if v}=={'A','F'}
    assert r['entry_index']==253 and r['exit_index']==274
