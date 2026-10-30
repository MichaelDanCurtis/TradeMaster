"""Local, content-addressed uploads. Uploading never calls the model."""
import asyncio
from datetime import date
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field

from tradingagents.research.contracts import content_hash
from tradingagents.research.data.store import ArtifactStore
from tradingagents.ui.models import new_id, now_utc

ROOT = Path(__file__).resolve().parents[2]
MAX_BYTES = 10*1024*1024
_RENDER_LOCK = threading.Lock()


class EvidenceAttachment(SQLModel, table=True):
    __tablename__ = 'ui_evidence_attachments'
    id: str = Field(default_factory=lambda: new_id('attachment'), primary_key=True)
    symbol: str = Field(index=True)
    manifest: dict = Field(sa_column=Column(JSON, nullable=False))
    manifest_hash: str


def attachment_store():
    return ArtifactStore(ROOT/'.research-artifacts/evidence-attachments/objects')


def selected_pages(value):
    if not re.fullmatch(r'[1-9][0-9]{0,2}(,[1-9][0-9]{0,2}){0,3}', value):
        raise ValueError('Choose up to four page numbers, for example 1,2')
    pages = [int(p) for p in value.split(',')]
    if len(set(pages)) != len(pages):
        raise ValueError('Page numbers must be unique')
    return pages


def load_attachment(sessions, identifier, symbol=None):
    with sessions() as session:
        row = session.get(EvidenceAttachment, identifier)
        if not row or (symbol is not None and row.symbol != symbol):
            raise ValueError('Attachment not found for this ticker')
        if content_hash(row.manifest) != row.manifest_hash:
            raise ValueError('Attachment manifest fingerprint differs')
        return row


def attachment_sources(sessions, identifiers, symbol):
    store = attachment_store()
    sources = []
    for index, identifier in enumerate(identifiers):
        row = load_attachment(sessions, identifier, symbol)
        manifest = row.manifest
        store.get(manifest['original_sha256'])
        for page in manifest['pages']:
            store.get(page['image_sha256'])
            source_id = f'attachment_{index+1}_p{page["page"]}'
            sources.append({'source_id': source_id, 'title': f'{manifest["filename"]} · page {page["page"]}',
                'publisher': 'User-supplied document; publisher and ticker identity unverified',
                'kind': manifest['kind'], 'published_at': None, 'retrieved_at': manifest['uploaded_at'],
                'declared_date': manifest['published_on'], 'data_as_of': None, 'url': None,
                'origin': manifest['original_sha256'], 'attachment_id': row.id, 'page': page['page'],
                'original_sha256': manifest['original_sha256'], 'image_sha256': page['image_sha256'],
                'width': page['width'], 'height': page['height'],
                'text': f'User-supplied attachment for review of {symbol}; identity is not verified. '
                        f'User-declared document date: {manifest["published_on"] or "unknown"}. '
                        'Only this selected page/image was supplied. Visual readings are approximate, not verified market data.\n'
                        + ('Embedded PDF text (not OCR; may omit or misorder chart labels):\n'+page['text'] if page['text'] else 'No machine-extracted text is available.')})
    if len(sources) > 4:
        raise ValueError('A review can include at most four selected pages/images')
    return sources


def create_attachment(sessions, data, symbol, filename, pages, published_on):
    if not _RENDER_LOCK.acquire(blocking=False):
        raise ValueError('Another attachment is being prepared; try again when it finishes')
    try:
        with tempfile.TemporaryDirectory(prefix='evidence-render-') as directory:
            folder = Path(directory); original = folder/'original'
            original.write_bytes(data)
            env = {k:v for k,v in os.environ.items() if k in ('PATH','TMPDIR','LANG','SYSTEMROOT')}
            try:
                subprocess.run([sys.executable, '-I', str(ROOT/'scripts/research/render_evidence.py'),
                    str(original), str(folder), json.dumps(pages)], env=env, cwd=folder,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25, check=True)
            except (subprocess.SubprocessError, OSError):
                raise ValueError('Cannot prepare this file. Check the page numbers, use an unencrypted PDF or static PNG/JPEG, and keep images below 20 megapixels.') from None
            rendered = json.loads((folder/'result.json').read_text())
            store = attachment_store()
            manifest = {'filename': filename, 'uploaded_at': now_utc().isoformat(), 'published_on': published_on,
                'original_sha256': store.put(data), 'original_bytes': len(data),
                'mime': rendered['mime'], 'kind': rendered['kind'], 'page_count': rendered['page_count'],
                'renderer': {'versions': rendered['versions'], 'long_edge_limit': 1800,
                    'aspect_ratio_preserved': True, 'script_sha256': __import__('hashlib').sha256((ROOT/'scripts/research/render_evidence.py').read_bytes()).hexdigest()}, 'pages': []}
            for page in rendered['pages']:
                manifest['pages'].append({k:v for k,v in page.items() if k != 'file'} | {'image_sha256': store.put((folder/page['file']).read_bytes())})
            row = EvidenceAttachment(symbol=symbol, manifest=manifest, manifest_hash=content_hash(manifest))
            with sessions() as session:
                session.add(row); session.commit()
            return {'id': row.id, 'symbol': symbol, 'manifest': manifest, 'manifest_hash': row.manifest_hash}
    finally:
        _RENDER_LOCK.release()


def create_attachment_router(sessions):
    router = APIRouter(prefix='/attachments')

    @router.post('', status_code=201)
    async def upload(request: Request, symbol: str, filename: str, pages: str = '1', published_on: str | None = None):
        try:
            if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}', symbol):
                raise ValueError('Enter a valid ticker before attaching a file')
            if not 1 <= len(filename) <= 180 or any(ord(c)<32 for c in filename) or '/' in filename or '\\' in filename:
                raise ValueError('Use a plain filename of at most 180 characters')
            page_numbers = selected_pages(pages)
            if published_on:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', published_on) or date.fromisoformat(published_on) > now_utc().date():
                    raise ValueError('Use a document date in YYYY-MM-DD format that is not in the future')
            data = bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise HTTPException(413, 'File exceeds the 10 MB upload limit')
            if not data:
                raise ValueError('The selected file is empty')
            return await asyncio.to_thread(create_attachment, sessions, bytes(data), symbol, filename, page_numbers, published_on)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @router.get('/{identifier}/{part}')
    def download(identifier: str, part: str):
        try:
            row = load_attachment(sessions, identifier)
            if part == 'original':
                digest, mime = row.manifest['original_sha256'], row.manifest['mime']
            else:
                page = next(p for p in row.manifest['pages'] if part == f'page-{p["page"]}.png')
                digest, mime = page['image_sha256'], 'image/png'
            data = attachment_store().get(digest)
            extension = {'application/pdf':'pdf', 'image/png':'png', 'image/jpeg':'jpg'}[mime]
            return Response(data, media_type=mime, headers={'Content-Disposition': f'attachment; filename="original-evidence.{extension}"' if part == 'original' else 'inline',
                'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'})
        except (ValueError, StopIteration, OSError):
            raise HTTPException(404, 'Attachment or page unavailable') from None

    return router
