"""Read-only company identity, dated holders and chart data for Market Pulse."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from tradingagents.ui.models import now_utc
from tradingagents.ui.explorer_briefs import safe_url
from tradingagents.ui.market_pulse import number

SYMBOL = re.compile(r'^[A-Z][A-Z0-9.\-]{0,11}$')


def clean_symbol(value):
    value = value.strip().upper()
    if not SYMBOL.fullmatch(value): raise HTTPException(422, 'Invalid stock symbol')
    return value


def text(value, limit=200):
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def report_date(value, now):
    try:
        if isinstance(value, bool): return None
        if isinstance(value, (int, float)):
            date = datetime.fromtimestamp(value, timezone.utc).date()
        else:
            date = datetime.fromisoformat(str(value).replace('Z', '+00:00')).date()
        return date.isoformat() if date <= now.date() else None
    except (ValueError, TypeError, OverflowError, OSError): return None


def fraction(value):
    value = number(value)
    return value * 100 if value is not None and 0 <= value <= 1 else None


def public_company(symbol):
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'SYSTEMROOT') if k in os.environ}
    env['PYTHON_DOTENV_DISABLED'] = '1'
    result = subprocess.run([sys.executable, '-m', 'tradingagents.ui.market_identity_child', symbol],
        cwd=Path(__file__).resolve().parents[2], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=25)
    if result.returncode or len(result.stdout) > 200000: raise ValueError('Company lookup unavailable')
    return json.loads(result.stdout)


def normalize_company(symbol, raw, now):
    info = raw.get('info') or {}
    # Do not quietly substitute an issuer's common shares for its warrant or another share class.
    if info.get('symbol') != symbol or not (text(info.get('longName')) or text(info.get('shortName'))):
        raise ValueError('Company identity mismatch')
    holders, insiders = [], []
    for row in raw.get('institutional', [])[:50]:
        name = text(row.get('Holder')); date = report_date(row.get('Date Reported'), now)
        shares = number(row.get('Shares'))
        if name and date and shares is not None and shares > 0:
            holders.append({'name': name, 'reported_at': date, 'shares': shares, 'percent': fraction(row.get('pctHeld'))})
    for row in raw.get('insiders', [])[:50]:
        name = text(row.get('Name'))
        for key, date_key, kind in [('Shares Owned Directly','Position Direct Date','direct'),('Shares Owned Indirectly','Position Indirect Date','indirect')]:
            shares = number(row.get(key)); date = report_date(row.get(date_key), now)
            if name and date and shares is not None and shares > 0:
                insiders.append({'name': name, 'position': text(row.get('Position')), 'reported_at': date, 'shares': shares, 'holding_type': kind})
    holders.sort(key=lambda r: r['shares'], reverse=True)
    insiders.sort(key=lambda r: r['shares'], reverse=True)
    description = ' '.join(str(info.get('longBusinessSummary') or '').split()[:100])
    metrics = {key: number(info.get(field)) for key, field in {'market_cap':'marketCap','enterprise_value':'enterpriseValue',
        'trailing_pe':'trailingPE','forward_pe':'forwardPE','eps':'trailingEps','revenue':'totalRevenue',
        'profit_margin':'profitMargins','revenue_growth':'revenueGrowth','free_cash_flow':'freeCashflow',
        'cash':'totalCash','debt':'totalDebt','employees':'fullTimeEmployees'}.items()}
    return {'symbol': symbol, 'status': 'available', 'retrieved_at': now.isoformat(),
        'name': text(info.get('longName')) or text(info.get('shortName')), 'description': description,
        'sector': text(info.get('sector')), 'industry': text(info.get('industry')), 'country': text(info.get('country')),
        'website': safe_url(str(info.get('website') or '')), 'security_type': text(info.get('quoteType')),
        'parent': text(info.get('parentCompany')), 'fund_family': text(info.get('fundFamily')), 'currency': text(info.get('currency')),
        'insider_percent': fraction(info.get('heldPercentInsiders')), 'institutional_percent': fraction(info.get('heldPercentInstitutions')),
        'holders': holders[:10], 'insiders': insiders[:10], 'metrics': metrics,
        'profile_url': f'https://finance.yahoo.com/quote/{symbol}/profile/',
        'holders_url': f'https://finance.yahoo.com/quote/{symbol}/holders/',
        'gaps': raw.get('gaps', []),
        'ownership_note': 'Reported positions can be months old and overlap. They are not a complete ownership register or proof of control. Aggregate ownership percentages have no supplied report date.'}


class CachedLookup:
    def __init__(self):
        self.values = OrderedDict()
        self.lock = threading.Lock()
        self.stripes = [threading.Lock() for _ in range(32)]

    def get(self, key, lookup, ttl):
        with self.stripes[hash(key) % len(self.stripes)]:
            with self.lock:
                saved = self.values.get(key)
                if saved and saved[0] > time.monotonic(): return saved[1]
            result = lookup()
            with self.lock:
                self.values[key] = (time.monotonic() + (ttl if result['status'] == 'available' else 60), result)
                self.values.move_to_end(key)
                while len(self.values) > 256: self.values.popitem(last=False)
            return result


class InstrumentService:
    def __init__(self, market_factory, company_fetcher=public_company):
        self.market_factory, self.company_fetcher = market_factory, company_fetcher
        self.cache = CachedLookup()

    def identity(self, symbol):
        symbol = clean_symbol(symbol)
        def lookup():
            at = now_utc().isoformat()
            try:
                provider, _ = self.market_factory()
                asset = provider.asset_metadata(symbol)
                if asset.get('symbol') != symbol or not text(asset.get('name')): raise ValueError('Identity mismatch')
                name = text(asset['name'])
                kind = 'Warrant' if re.search(r'\bwarrants?\b', name, re.I) else 'Preferred shares' if re.search(r'\bpreferred\b', name, re.I) else 'Listed security'
                return {'symbol': symbol, 'name': name, 'exchange': text(asset.get('exchange')),
                    'asset_class': text(asset.get('class')), 'security_type': kind,
                    'status': 'available', 'retrieved_at': at, 'source': 'Alpaca asset directory'}
            except Exception:
                return {'symbol': symbol, 'name': None, 'exchange': None, 'status': 'unavailable', 'retrieved_at': at,
                        'source': 'Alpaca asset directory', 'security_type': 'Unverified security'}
        return self.cache.get('identity:'+symbol, lookup, 86400)

    def company(self, symbol):
        symbol = clean_symbol(symbol)
        def lookup():
            try:
                return normalize_company(symbol, self.company_fetcher(symbol), now_utc())
            except Exception:
                return {'symbol': symbol, 'status': 'unavailable', 'name': None, 'retrieved_at': now_utc().isoformat(),
                        'holders': [], 'insiders': [], 'metrics': {}, 'gaps': ['Company and ownership details could not be verified for this exact symbol. No parent or shareholder was inferred.']}
        return self.cache.get('company:'+symbol, lookup, 21600)

    def chart(self, symbol, range):
        symbol = clean_symbol(symbol)
        def lookup():
            at = now_utc()
            days, timeframe, interval, sessions = {'1D':(5,'1Min','1m',1), '5D':(12,'15Min','15m',5),
                '1M':(32,'1Hour','1h',None), '1Y':(366,'1Day','1d',None)}[range]
            try:
                provider, config = self.market_factory(); feed = config.get('feed') or 'iex'
                raw = provider.historical_bars(symbol=symbol, start=at-timedelta(days=days), end=at, timeframe=timeframe,limit=10000,feed=feed)
                bars = {}
                for bar in raw:
                    if bar.symbol != symbol or bar.timestamp.tzinfo is None or bar.timestamp > at or bar.timestamp < at-timedelta(days=days): continue
                    values = [number(getattr(bar,k),positive=True) for k in ('open','high','low','close')]
                    vol = number(bar.volume)
                    if any(v is None for v in values) or vol is None or vol < 0: continue
                    opened, high, low, closed = values
                    if not low <= min(opened,closed) <= max(opened,closed) <= high: continue
                    stamp=bar.timestamp.astimezone(timezone.utc).isoformat()
                    bars[stamp]={'symbol':symbol,'provider':'alpaca','feed':feed,'interval':interval,'timestamp':stamp,
                        'open':opened,'high':high,'low':low,'close':closed,'volume':vol}
                ordered=[bars[k] for k in sorted(bars)]
                if sessions:
                    dates=sorted({datetime.fromisoformat(b['timestamp']).astimezone(ZoneInfo('America/New_York')).date() for b in ordered})[-sessions:]
                    ordered=[b for b in ordered if datetime.fromisoformat(b['timestamp']).astimezone(ZoneInfo('America/New_York')).date() in dates]
                return {'symbol':symbol,'range':range,'feed':feed,'bars':ordered,'status':'available' if ordered else 'unavailable',
                    'retrieved_at':at.isoformat(),'as_of':ordered[-1]['timestamp'] if ordered else None}
            except Exception:
                return {'symbol':symbol,'range':range,'bars':[],'status':'unavailable','retrieved_at':at.isoformat(),'as_of':None,'feed':None}
        return self.cache.get('chart:'+symbol+':'+range, lookup, 60)


def install_instrument_routes(router, market_factory):
    service = InstrumentService(market_factory)

    @router.get('/identities')
    def identities(symbols: str):
        names = list(dict.fromkeys(clean_symbol(s) for s in symbols.split(',')))
        if len(names) > 64: raise HTTPException(422, 'Choose at most 64 symbols')
        with ThreadPoolExecutor(max_workers=4) as pool:
            return {'items': list(pool.map(service.identity, names))}

    @router.get('/company/{symbol}')
    def company(symbol: str): return service.company(symbol)

    @router.get('/chart/{symbol}')
    def chart(symbol: str, range: Literal['1D','5D','1M','1Y'] = '1M'): return service.chart(symbol, range)
