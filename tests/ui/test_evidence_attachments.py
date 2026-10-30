from io import BytesIO
from pathlib import Path
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from tradingagents.research.contracts import content_hash
from tradingagents.research.data.store import ArtifactStore
from tradingagents.ui import evidence_attachments as attachments
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.explorer_briefs import BriefRequest, validate_brief
from tests.ui.test_explorer_briefs import BINDING, completion, output

FIXTURE = Path(__file__).parents[1]/'fixtures/evidence/chart.pdf'


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine, sessions = create_session_factory('sqlite:///'+str(tmp_path/'attachments.db'))
    init_db(engine)
    store = ArtifactStore(tmp_path/'objects')
    monkeypatch.setattr(attachments, 'attachment_store', lambda: store)
    app = FastAPI(); app.include_router(attachments.create_attachment_router(sessions))
    return TestClient(app), sessions, store


def upload(api, data, **params):
    return api[0].post('/attachments', params={'symbol':'TEST','filename':'chart.pdf', **params}, content=data)


def png():
    stream=BytesIO();Image.new('RGB',(300,100),'white').save(stream,format='PNG');return stream.getvalue()


def test_pdf_selected_page_original_and_render_integrity(api):
    response=upload(api,FIXTURE.read_bytes(),pages='1',published_on='2026-01-01')
    assert response.status_code==201,response.text
    result=response.json();manifest=result['manifest'];identifier=result['id']
    assert manifest['page_count']==2 and [p['page'] for p in manifest['pages']]==[1]
    assert 'SYNTHETIC TEST' in manifest['pages'][0]['text'] and 'PAGE TWO' not in manifest['pages'][0]['text']
    assert max(manifest['pages'][0]['width'],manifest['pages'][0]['height'])<=1800
    assert api[0].get(f'/attachments/{identifier}/original').content==FIXTURE.read_bytes()
    image=api[0].get(f'/attachments/{identifier}/page-1.png')
    assert image.headers['content-type']=='image/png' and image.content.startswith(b'\x89PNG')
    assert api[0].get(f'/attachments/{identifier}/page-2.png').status_code==404
    sources=attachments.attachment_sources(api[1],[identifier],'TEST')
    assert sources[0]['published_at'] is None and sources[0]['declared_date']=='2026-01-01'
    assert sources[0]['kind']=='pdf_page' and sources[0]['image_sha256']==manifest['pages'][0]['image_sha256']
    with pytest.raises(ValueError,match='ticker'):attachments.attachment_sources(api[1],[identifier],'NVDA')
    assert content_hash(manifest)==result['manifest_hash']


def test_image_preserves_aspect_ratio_and_rejects_nonimage(api):
    result=upload(api,png(),filename='chart.png').json()
    assert result['manifest']['kind']=='chart_image'
    page=result['manifest']['pages'][0];assert page['width']/page['height']==3
    assert upload(api,b'<svg onload="danger()"/>',filename='chart.png').status_code==422
    assert upload(api,b'').status_code==422
    assert upload(api,png(),pages='2').status_code==422


@pytest.mark.parametrize('pages',['0','1,1','1,2,3,4,5','1-3','9999','../1'])
def test_invalid_page_requests_are_rejected_before_render(api,pages):
    assert upload(api,b'ignored',pages=pages).status_code==422


def test_bad_pdf_page_date_filename_and_size_are_rejected(api):
    assert upload(api,FIXTURE.read_bytes(),pages='3').status_code==422
    assert upload(api,png(),published_on='2099-01-01').status_code==422
    assert upload(api,png(),filename='../escape.pdf').status_code==422
    assert upload(api,b'x'*(attachments.MAX_BYTES+1)).status_code==413


def test_two_files_cannot_exceed_four_selected_pages(api):
    first=upload(api,FIXTURE.read_bytes(),pages='1,2').json()
    second=upload(api,FIXTURE.read_bytes(),pages='1,2').json()
    assert len(attachments.attachment_sources(api[1],[first['id'],second['id']],'TEST'))==4
    with pytest.raises(ValueError,match='at most four'):
        attachments.attachment_sources(api[1],[first['id'],second['id'],first['id']],'TEST')
    with pytest.raises(ValueError):
        BriefRequest(symbol='TEST',idempotency_key='x'*16,provider_config_hash='a'*64,
                     attachment_ids=[first['id'],second['id'],first['id']])


def test_visual_references_are_not_validated_as_exact_text():
    packet={'sources':[{'source_id':'attachment_1_p1','kind':'chart_image','text':'User-supplied image'}]}
    proposal=output();claim={'kind':'inference','text':'The Q2 bar appears tallest.',
        'citations':[{'source_id':'attachment_1_p1','quote':None,'region':'Q2 bar at the center'}]}
    proposal.update(overview=claim,catalysts=[],bull_case=[],bear_case=[])
    assert validate_brief(completion(proposal),packet,BINDING)['proposal']
    claim['kind']='observation'
    assert validate_brief(completion(proposal),packet,BINDING)['proposal'] is None
    claim['kind']='inference';claim['citations'][0]['quote']='Invented exact price'
    assert validate_brief(completion(proposal),packet,BINDING)['proposal'] is None
    claim['citations'][0]['quote']=None;packet['sources'][0]['kind']='news'
    assert validate_brief(completion(proposal),packet,BINDING)['proposal'] is None


def test_corrupt_attachment_manifest_is_not_served(api):
    result=upload(api,png(),filename='chart.png').json()
    with api[1]() as session:
        row=session.get(attachments.EvidenceAttachment,result['id']);row.manifest_hash='0'*64
        session.add(row);session.commit()
    assert api[0].get(f'/attachments/{result["id"]}/original').status_code==404
