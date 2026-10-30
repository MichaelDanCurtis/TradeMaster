"""Lossless storage of cumulative accounting reports; legacy JSON stays readable."""
import base64
import hashlib
import json
import zlib

from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator

MARKER = '_trademaster_accounting_storage'
VERSION = 'zlib_json_v1'
THRESHOLD = 64 * 1024
MAX_BYTES = 128 * 1024 * 1024
SUMMARY_FIELDS = ('reconciled', 'evidence_kind', 'account_key', 'baseline_id')


def encode_report(report):
    if not isinstance(report, dict) or MARKER in report:
        raise ValueError('Expected an unpacked accounting report')
    raw = json.dumps(report, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(raw) > MAX_BYTES:
        raise ValueError('Accounting report exceeds the bounded storage size')
    if len(raw) < THRESHOLD:
        return report
    compressed = zlib.compress(raw)
    if len(compressed) * 2 > len(raw):
        return report
    return {MARKER: VERSION, 'sha256': hashlib.sha256(raw).hexdigest(), 'uncompressed_bytes': len(raw),
        'payload': base64.b64encode(compressed).decode('ascii'),
        **{key: report.get(key) for key in SUMMARY_FIELDS}}


def decode_report(stored):
    if not isinstance(stored, dict):
        raise ValueError('Accounting report must be an object')
    if MARKER not in stored:
        return stored
    try:
        if stored[MARKER] != VERSION:
            raise ValueError('Unknown accounting storage version')
        size = stored['uncompressed_bytes']
        if type(size) is not int or not 0 < size <= MAX_BYTES:
            raise ValueError('Invalid accounting storage size')
        payload = stored['payload']
        if not isinstance(payload, str) or len(payload) > MAX_BYTES * 2:
            raise ValueError('Invalid compressed accounting payload')
        compressed = base64.b64decode(payload, validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, size + 1)
        if len(raw) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('Accounting storage length or stream mismatch')
        if hashlib.sha256(raw).hexdigest() != stored['sha256']:
            raise ValueError('Accounting storage fingerprint mismatch')
        report = json.loads(raw)
        if not isinstance(report, dict) or MARKER in report:
            raise ValueError('Invalid decoded accounting report')
        if any(stored.get(key) != report.get(key) for key in SUMMARY_FIELDS):
            raise ValueError('Accounting storage summary mismatch')
        return report
    except (KeyError, TypeError, UnicodeError, zlib.error) as exc:
        raise ValueError('Corrupt accounting report storage') from exc


class AccountingReportJSON(TypeDecorator):
    """Store a JSON envelope while returning the same public report dictionary."""
    impl = JSON
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encode_report(value)

    def process_result_value(self, value, dialect):
        return decode_report(value)
