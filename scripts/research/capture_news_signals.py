"""Bounded, read-only Alpaca news capture with immutable response evidence.

Historical API responses are current article versions, not a revision archive.
Downstream research must respect updated_at as well as created_at.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ENDPOINT = "https://data.alpaca.markets/v1beta1/news"
MAX_RESPONSE_BYTES = 5_000_000


def _utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("start and end must be timezone-aware RFC3339 timestamps")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc)


def _query(symbols, start, end):
    if not isinstance(symbols, (list, tuple)) or not 1 <= len(symbols) <= 100:
        raise ValueError("Provide between 1 and 100 stock symbols")
    if any(not isinstance(s, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", s) for s in symbols):
        raise ValueError("Invalid stock symbol")
    if len(set(symbols)) != len(symbols):
        raise ValueError("Duplicate stock symbols")
    if _date(start) >= _date(end):
        raise ValueError("start must precede end")
    return {"symbols": ",".join(symbols), "start": start, "end": end,
            "limit": 50, "include_content": "false", "sort": "asc"}


def _save(root, receipt):
    temporary = root / "receipt.tmp"
    temporary.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    temporary.replace(root / "receipt.json")


def capture(root, symbols, start, end, headers, client=None, max_pages=100):
    """Capture into a new directory and return its complete/truncated/failed receipt.

    Caller-owned clients are not closed. Errors after directory creation are
    recorded without exception messages, URLs from errors, response bodies, or
    credential headers. Existing directories are always refused, including empty
    ones. Pagination exhaustion means API traversal completed, not guaranteed
    coverage of all historical news or original article revisions.
    """
    query = _query(symbols, start, end)
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= 10000:
        raise ValueError("max_pages must be an integer between 1 and 10000")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    receipt = {
        "schema_version": 1, "provider": "alpaca_benzinga", "endpoint": ENDPOINT,
        "query": query, "max_pages": max_pages, "status": "failed", "complete": False,
        "first_request_started_at": None, "last_retrieved_at": None,
        "pages": [], "attempts": [], "article_count": 0,
        "failure": {"code": "incomplete_capture"},
        "qualification": "API traversal only; historical responses can contain revised articles. Preserve created_at and updated_at.",
    }
    _save(root, receipt)
    owned = client is None
    client = client or httpx.Client(timeout=35, follow_redirects=False)
    params = dict(query)
    seen_tokens = set()
    try:
        for page in range(1, max_pages + 1):
            for attempt in range(1, 4):
                started = _utc()
                if receipt["first_request_started_at"] is None:
                    receipt["first_request_started_at"] = started
                entry = {"page": page, "attempt": attempt, "request_started_at": started,
                         "retrieved_at": None, "status_code": None}
                receipt["attempts"].append(entry)
                _save(root, receipt)
                response = client.get(ENDPOINT, params=dict(params), headers=headers,
                                      follow_redirects=False, timeout=35)
                retrieved = _utc()
                entry.update(retrieved_at=retrieved, status_code=response.status_code)
                receipt["last_retrieved_at"] = retrieved
                _save(root, receipt)
                if response.status_code != 429 or attempt == 3:
                    break
                time.sleep(min(5, attempt))
            if response.status_code != 200:
                receipt["failure"] = {"code": "http_error", "status_code": response.status_code}
                break
            raw = response.content
            if len(raw) > MAX_RESPONSE_BYTES:
                receipt["failure"] = {"code": "response_size_limit"}
                break
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                receipt["failure"] = {"code": "invalid_json"}
                break
            if (not isinstance(payload, dict) or not isinstance(payload.get("news"), list)
                    or any(not isinstance(row, dict) for row in payload["news"])
                    or len(payload["news"]) > 50):
                receipt["failure"] = {"code": "invalid_news_schema"}
                break
            token = payload.get("next_page_token")
            if token is not None and (not isinstance(token, str) or len(token) > 4096):
                receipt["failure"] = {"code": "invalid_page_token"}
                break
            filename = f"page-{page:06d}.json"
            with (root / filename).open("xb") as handle:
                handle.write(raw)
            receipt["pages"].append({"file": filename, "sha256": hashlib.sha256(raw).hexdigest(),
                                     "bytes": len(raw), "request_started_at": started,
                                     "retrieved_at": retrieved, "params": dict(params),
                                     "article_count": len(payload["news"])})
            receipt["article_count"] += len(payload["news"])
            if not token:
                receipt.update(status="complete", complete=True, failure=None)
                break
            if token in seen_tokens:
                receipt["failure"] = {"code": "repeated_page_token"}
                break
            seen_tokens.add(token)
            if page == max_pages:
                receipt.update(status="truncated", failure={"code": "max_pages"})
                break
            params["page_token"] = token
            _save(root, receipt)
    except httpx.TransportError:
        receipt["failure"] = {"code": "transport_error"}
    except Exception:
        # Never persist a provider exception: it can contain request credentials.
        receipt["failure"] = {"code": "capture_error"}
    finally:
        _save(root, receipt)
        if owned:
            client.close()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--symbols", required=True, help="Comma-separated uppercase stock symbols")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--max-pages", type=int, default=100)
    args = parser.parse_args()
    engine = None
    try:
        from scripts.research.capture_prediction_improvements import provider
        _query(args.symbols.split(","), args.start, args.end)
        if args.root.exists():
            raise ValueError("Capture directory already exists")
        headers, engine = provider()
        receipt = capture(args.root, args.symbols.split(","), args.start, args.end,
                          headers, max_pages=args.max_pages)
        print(json.dumps({"status": receipt["status"], "pages": len(receipt["pages"]),
                          "article_count": receipt["article_count"], "failure": receipt["failure"]}))
        return 0 if receipt["complete"] else 1
    except Exception:
        print(json.dumps({"status": "failed", "failure": {"code": "configuration_or_capture_error"}}))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
