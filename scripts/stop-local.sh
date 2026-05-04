#!/usr/bin/env bash
set -euo pipefail

API_SESSION="${TRADEMASTER_API_SESSION:-trademaster-api}"
WEB_SESSION="${TRADEMASTER_WEB_SESSION:-wealth-agents-web}"

tmux kill-session -t "${API_SESSION}" 2>/dev/null || true
tmux kill-session -t "${WEB_SESSION}" 2>/dev/null || true

echo "Stopped ${API_SESSION} and ${WEB_SESSION} if they were running."
