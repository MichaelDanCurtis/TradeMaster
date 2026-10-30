#!/usr/bin/env bash
set -euo pipefail
sessions=("${TRADEMASTER_SCHEDULER_SESSION:-trademaster-scheduler}" "${TRADEMASTER_RESEARCH_SESSION:-trademaster-research}" "${TRADEMASTER_DEPLOYMENT_SESSION:-trademaster-deployments}" "${TRADEMASTER_API_SESSION:-trademaster-api}" "${TRADEMASTER_WEB_SESSION:-wealth-agents-web}")
# Let workers close children and write stopped receipts before removing sessions.
for session in "${sessions[@]}"; do
  tmux send-keys -t "$session" C-c 2>/dev/null || true
done
for _ in {1..30}; do
  remaining=0
  for session in "${sessions[@]}"; do
    if tmux has-session -t "$session" 2>/dev/null; then remaining=1; fi
  done
  [[ "$remaining" == 0 ]] && break
  sleep .1
done
for session in "${sessions[@]}"; do
  tmux kill-session -t "$session" 2>/dev/null || true
done
echo "Stopped local API, web, research, deployment and scheduler sessions."
