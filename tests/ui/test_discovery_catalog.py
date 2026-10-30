from copy import deepcopy
import json
import pytest
from fastapi import HTTPException
from tradingagents.research.data.store import ArtifactStore
from tradingagents.ui.discovery_catalog import DiscoveryCatalog, RecipeRequest, parse_directory
from tradingagents.ui.opportunity_lab import OpportunityLab, ScanRequest
from tradingagents.ui.research_desk import Desk
from tradingagents.ui.db import create_session_factory, init_db


@pytest.fixture
def catalog(tmp_path):
    _, sessions = create_session_factory('sqlite:///' + str(tmp_path / 'test.db')); init_db(sessions.kw['bind'])
    class Sources:
        store = ArtifactStore(tmp_path / 'sources')
        rows = [[i+1, f'Issuer {i}', 'A'+chr(65+i//26)+chr(65+i%26), 'NYSE'] for i in range(60)]
        wrong = False
        def read(self, url):
            raw = {'fields': ['cik', 'name', 'ticker', 'exchange'], 'data': self.rows}
            return raw, {'url':url, 'sha256':self.store.put(json.dumps(raw).encode()), 'retrieved_at':'2026-09-07T00:00:00+00:00'}
        def collect(self, symbol):
            cik = next(r[0] for r in self.rows if r[2] == symbol)
            return {'cik': -1 if self.wrong else cik, 'profile': {}, 'metrics': {'revenue_growth':20,'net_margin':10},
                    'financials':{}, 'filings':[], 'sources':[], 'gaps':[], 'security_type':'unverified'}
    lab = OpportunityLab(Desk(sessions, Sources()), lambda:None, tmp_path / 'objects')
    return DiscoveryCatalog(lab)


def test_directory_counts_duplicates_conflicts_and_unknown_exchange():
    rows = [[1,'A','AAA','NYSE'],[1,'A','AAA','NYSE'],[2,'B','BBB','Nasdaq'],[3,'B','BBB','Nasdaq'],
            [4,'C','CCC',None],[True,'Bad','DDD','NYSE'],[1,'Bad','../evil','NYSE'],['malformed']]
    result = parse_directory({'fields':['cik','name','ticker','exchange'], 'data':rows})
    assert [e['symbol'] for e in result['entries']] == ['AAA','CCC']
    assert result['exchange_counts'] == {'NYSE':1,'Unreported':1}
    assert result['input_rows']==8 and len(result['excluded'])==5


def test_recipe_freezes_membership_and_runs_more_than_40(catalog):
    universe = catalog.capture(); data = catalog.universe(universe['id'])
    symbols = [e['symbol'] for e in data['entries']]
    recipe = catalog.save_recipe(RecipeRequest(name='All sixty', symbols=symbols, universe_id=universe['id'], require_fcf=False))
    # A later directory does not silently alter the recipe or its issuer identities.
    catalog.desk.sources.rows = deepcopy(catalog.desk.sources.rows) + [[100,'New','NEW','NYSE']]
    catalog.capture()
    scan = catalog.run(recipe['id'])
    for _ in range(60): catalog.lab.tick()
    result = catalog.desk.get(scan['id'],'opportunity_scan')['payload']
    assert result['processed']==60 and result['state']=='completed' and not result['failures']
    assert len(result['results'])==60 and len(result['symbols'])==60
    assert result['recipe_hash']==recipe['payload']['artifact_hash']
    assert all(c['directory_membership']['cik']>0 for c in result['results'])
    again = catalog.run(recipe['id']); catalog.lab.tick()
    c=catalog.desk.get(again['id'],'opportunity_scan')['payload']['results'][0]
    assert c['previous_snapshot_id'] is not None


def test_recipe_rejects_foreign_membership_and_issuer_drift(catalog):
    u=catalog.capture()
    with pytest.raises(HTTPException): catalog.save_recipe(RecipeRequest(name='Bad',symbols=['FOREIGN'],universe_id=u['id']))
    r=catalog.save_recipe(RecipeRequest(name='One',symbols=['AAA'],universe_id=u['id']))
    catalog.desk.sources.wrong=True
    scan=catalog.run(r['id']);catalog.lab.tick()
    result=catalog.desk.get(scan['id'],'opportunity_scan')['payload']
    assert not result['results'] and len(result['failures'])==1


def test_corrupt_recipe_or_directory_blocks_scan_without_side_effects(catalog):
    u=catalog.capture();r=catalog.save_recipe(RecipeRequest(name='One',symbols=['AAA'],universe_id=u['id']))
    catalog.lab.store.path(r['payload']['artifact_hash']).write_bytes(b'bad')
    with pytest.raises(HTTPException): catalog.run(r['id'])
    assert not catalog.desk.rows('opportunity_scan')
    catalog.desk.sources.store.path(u['payload']['source']['sha256']).write_bytes(b'bad')
    with pytest.raises(HTTPException): catalog.universe(u['id'])


def test_catalog_failure_sanitized_and_manual_recipe_supported(catalog):
    def fail(url):raise RuntimeError('secret provider internals')
    catalog.desk.sources.read=fail
    with pytest.raises(HTTPException) as exc: catalog.capture()
    assert 'secret' not in str(exc.value.detail)
    assert not catalog.desk.rows('discovery_universe')
    r=catalog.save_recipe(RecipeRequest(name=' Manual ',symbols=['AAA','AAA']))
    assert r['payload']['name']=='Manual' and r['payload']['symbols']==['AAA']
    assert r['payload']['membership']=={}


def test_resume_keeps_prior_evidence_and_never_retries_finished_symbols(catalog):
    u=catalog.capture();r=catalog.save_recipe(RecipeRequest(name='Two',symbols=['AAA','AAB'],universe_id=u['id']))
    scan=catalog.run(r['id']);catalog.lab.tick();catalog.lab.cancel(scan['id'])
    first=catalog.desk.get(scan['id'],'opportunity_scan')['payload']['results'][0]['snapshot_id']
    catalog.lab.resume(scan['id']);catalog.lab.tick()
    done=catalog.desk.get(scan['id'],'opportunity_scan')['payload']
    assert done['state']=='completed' and done['processed']==2
    assert next(c for c in done['results'] if c['symbol']=='AAA')['snapshot_id']==first
    assert len(catalog.desk.rows('company'))==2
    with pytest.raises(HTTPException):catalog.lab.resume(scan['id'])


def test_resume_rejects_inflight_read_and_other_active_scan(catalog):
    row=catalog.lab.start_scan(ScanRequest(symbols=['AAA','AAB']))
    collect=catalog.desk.sources.collect
    def stop(symbol):
        catalog.lab.cancel(row['id'])
        with pytest.raises(HTTPException):catalog.lab.resume(row['id'])
        return collect(symbol)
    catalog.desk.sources.collect=stop;catalog.lab.tick()
    catalog.lab.start_scan(ScanRequest(symbols=['AAC']))
    with pytest.raises(HTTPException):catalog.lab.resume(row['id'])


def test_comparisons_do_not_cross_issuer_identity(catalog):
    from tradingagents.ui.opportunity_lab import rank_candidate
    from datetime import date
    current=catalog.desk.collect('AAA');prior=deepcopy(current)
    prior['payload']['cik']=999;prior['payload']['metrics']['revenue_growth']=0
    result=rank_candidate(current,prior,ScanRequest(symbols=['AAA']),date.today())
    assert result['previous_snapshot_id'] is None
    assert not any(r['kind']=='change' for r in result['reasons'])
    assert any('issuer identity' in g for g in result['gaps'])


def test_routes_page_directory_and_preserve_recipe_export(tmp_path):
    from tradingagents.ui.api import create_app
    from fastapi.testclient import TestClient
    app=create_app(database_url='sqlite:///'+str(tmp_path/'api.db'))
    with TestClient(app) as client:
        catalog=app.state.opportunity_lab.catalog
        raw={'fields':['cik','name','ticker','exchange'],'data':[[1,'A','AAA','NYSE'],[2,'B','BBB','Nasdaq']]}
        digest=catalog.desk.sources.store.put(json.dumps(raw).encode())
        catalog.desk.sources.read=lambda url:(raw,{'url':url,'sha256':digest,'retrieved_at':'2026-09-07T00:00:00+00:00'})
        root='/api/discover/opportunities'
        u=client.post(root+'/universes',json={});assert u.status_code==200
        uid=u.json()['id']
        page=client.get(root+f'/universes/{uid}?exchange=NYSE&limit=1').json()
        assert page['matched_count']==1 and page['entries'][0]['symbol']=='AAA'
        assert client.get(root+f'/universes/{uid}?limit=501').status_code==422
        assert client.get(root+f'/universes/{uid}/evidence.json').status_code==200
        r=client.post(root+'/recipes',json={'name':'One','symbols':['AAA'],'universe_id':uid})
        assert r.status_code==200
        rid=r.json()['id'];export=client.get(root+f'/recipes/{rid}/evidence.json')
        assert export.status_code==200 and export.json()['payload']==r.json()['payload']
        assert client.post(root+'/recipes',json={'name':'Bad','symbols':['CCC'],'universe_id':uid}).status_code==422
