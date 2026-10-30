"""Frozen SEC directory coverage and reusable research-only screening recipes."""
from __future__ import annotations

from collections import Counter, defaultdict
import re

from fastapi import HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from tradingagents.ui.opportunity_lab import ScanRequest
from tradingagents.ui.explorer_briefs import canonical_json

DIRECTORY_URL = 'https://www.sec.gov/files/company_tickers_exchange.json'


def parse_directory(raw):
    fields = raw.get('fields')
    if not isinstance(fields, list) or len(set(fields)) != len(fields) or not {'cik', 'name', 'ticker', 'exchange'} <= set(fields):
        raise ValueError('Unsupported SEC directory schema')
    rows = raw.get('data')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 50000:
        raise ValueError('Unsupported SEC directory size')
    grouped, excluded = defaultdict(list), []
    for i, values in enumerate(rows):
        if not isinstance(values, list) or len(values) != len(fields):
            excluded.append({'row': i, 'reason': 'Malformed directory row'}); continue
        row = dict(zip(fields, values))
        ticker, cik, name, exchange = (row.get(k) for k in ('ticker', 'cik', 'name', 'exchange'))
        if (not isinstance(ticker, str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}', ticker)
                or type(cik) is not int or not 0 < cik < 10**10 or not isinstance(name, str) or not name.strip()
                or (exchange is not None and (not isinstance(exchange, str) or not exchange.strip()))):
            excluded.append({'row': i, 'reason': 'Unusable ticker, issuer, name or exchange'}); continue
        grouped[ticker].append({'symbol': ticker, 'cik': cik, 'name': name.strip(), 'exchange': exchange or 'Unreported'})
    entries = []
    for ticker, matches in sorted(grouped.items()):
        # Do not choose between conflicting identities, even if one appears first.
        identities = {(m['cik'], m['name'], m['exchange']) for m in matches}
        if len(identities) != 1:
            excluded.append({'symbol': ticker, 'reason': 'Conflicting SEC directory entries'}); continue
        entries.append(matches[0])
        if len(matches) > 1:
            excluded.append({'symbol': ticker, 'reason': 'Duplicate identical entries collapsed', 'rows': len(matches)-1})
    if not entries:
        raise ValueError('No usable directory entries')
    return {'entries': entries, 'input_rows': len(rows), 'excluded': excluded,
            'exchange_counts': dict(sorted(Counter(e['exchange'] for e in entries).items()))}


class RecipeRequest(ScanRequest):
    name: str = Field(min_length=1, max_length=100)
    universe_id: str | None = None

    @field_validator('name')
    @classmethod
    def named(cls, value):
        if not value.strip(): raise ValueError('Name the screening recipe')
        return value.strip()


class DiscoveryCatalog:
    def __init__(self, lab):
        self.lab, self.desk = lab, lab.desk
        lab.catalog = self

    def capture(self):
        try:
            raw, source = self.desk.sources.read(DIRECTORY_URL)
            data = {**parse_directory(raw), 'source': source,
                    'scope': 'Current SEC ticker-to-issuer directory. It is not a complete market universe, historical membership record, common-stock classification or broker tradability check.'}
            digest = self.lab.store.put_json(data)
        except Exception:
            # Source transport failures must not expose provider internals.
            raise HTTPException(409, 'SEC directory capture failed. Existing saved coverage is unchanged.') from None
        return self.desk.save('discovery_universe', '', {'artifact_hash': digest, 'source': source,
            'member_count': len(data['entries']), 'input_rows': data['input_rows'], 'excluded_count': len(data['excluded']),
            'exchange_counts': data['exchange_counts'], 'scope': data['scope']})

    def universe(self, identifier):
        row = self.desk.get(identifier, 'discovery_universe')
        try:
            data = self.lab.store.json(row['payload']['artifact_hash'])
            self.desk.sources.store.get(data['source']['sha256'])
        except (ValueError, OSError):
            raise HTTPException(409, 'Saved SEC directory failed integrity verification') from None
        return data

    def save_recipe(self, request):
        symbols = list(dict.fromkeys(request.symbols))
        membership = {}
        universe_hash = None
        if request.universe_id:
            universe = self.universe(request.universe_id)
            known = {e['symbol']: e for e in universe['entries']}
            if any(s not in known for s in symbols):
                raise HTTPException(422, 'Every recipe symbol must belong to the selected saved SEC directory')
            membership = {s: known[s] for s in symbols}
            universe_hash = self.desk.get(request.universe_id, 'discovery_universe')['payload']['artifact_hash']
        frozen = {'name': request.name, 'symbols': symbols, 'min_growth': request.min_growth,
                  'min_margin': request.min_margin, 'require_fcf': request.require_fcf,
                  'universe_id': request.universe_id, 'universe_hash': universe_hash, 'membership': membership,
                  'execution_authority': False}
        digest = self.lab.store.put_json(frozen)
        return self.desk.save('screen_recipe', '', {**frozen, 'artifact_hash': digest})

    def recipe(self, identifier):
        row = self.desk.get(identifier, 'screen_recipe')
        try:
            frozen = self.lab.store.json(row['payload']['artifact_hash'])
            if frozen != {k: v for k, v in row['payload'].items() if k != 'artifact_hash'}:
                raise ValueError('Recipe metadata changed')
            if frozen.get('universe_id'):
                self.universe(frozen['universe_id'])
                if self.desk.get(frozen['universe_id'], 'discovery_universe')['payload']['artifact_hash'] != frozen['universe_hash']:
                    raise ValueError('Universe changed')
        except (ValueError, OSError):
            raise HTTPException(409, 'Saved recipe failed integrity verification') from None
        return row

    def run(self, identifier):
        recipe = self.recipe(identifier)
        return self.lab.start_scan(ScanRequest.model_validate(recipe['payload']), recipe=recipe)


def install_catalog_routes(router, lab):
    catalog = DiscoveryCatalog(lab)
    lab.catalog = catalog

    @router.get('/catalog')
    def index():
        return {'universes': lab.desk.rows('discovery_universe', limit=50),
                'recipes': lab.desk.rows('screen_recipe', limit=100)}

    @router.post('/universes')
    def capture():
        return catalog.capture()

    @router.get('/universes/{identifier}')
    def members(identifier: str, exchange: str = '', offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        data = catalog.universe(identifier)
        entries = [e for e in data['entries'] if not exchange or e['exchange'] == exchange]
        return {'entries': entries[offset:offset+limit], 'matched_count': len(entries), 'offset': offset,
                'limit': limit, 'total_count': len(data['entries']), 'source': data['source'], 'scope': data['scope']}

    @router.get('/universes/{identifier}/evidence.json')
    def export(identifier: str):
        return Response(canonical_json(catalog.universe(identifier)), media_type='application/json',
                        headers={'Content-Disposition': 'attachment; filename="sec-directory-evidence.json"'})

    @router.post('/recipes')
    def save(request: RecipeRequest):
        return catalog.save_recipe(request)

    @router.post('/recipes/{identifier}/scan')
    def scan(identifier: str):
        return catalog.run(identifier)

    @router.get('/recipes/{identifier}/evidence.json')
    def export_recipe(identifier: str):
        return Response(canonical_json(catalog.recipe(identifier)), media_type='application/json',
                        headers={'Content-Disposition': 'attachment; filename="screening-recipe.json"'})
