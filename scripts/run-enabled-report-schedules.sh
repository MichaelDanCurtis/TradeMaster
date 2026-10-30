#!/usr/bin/env bash
set -euo pipefail

API_BASE="${TRADEMASTER_API_BASE:-http://127.0.0.1:8797}"
SYMBOL="${1:-}"

url="${API_BASE%/}/api/report-schedules/trigger-enabled"
if [[ -n "${SYMBOL}" ]]; then
  url="${url}?symbol=${SYMBOL}"
fi

curl -fsS -X POST "${url}"
echo
