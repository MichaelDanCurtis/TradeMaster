#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${TRADEMASTER_API_PORT:-8797}"
WEB_PORT="${TRADEMASTER_WEB_PORT:-3000}"
API_SESSION="${TRADEMASTER_API_SESSION:-trademaster-api}"
WEB_SESSION="${TRADEMASTER_WEB_SESSION:-wealth-agents-web}"
RESEARCH_SESSION="${TRADEMASTER_RESEARCH_SESSION:-trademaster-research}"
DEPLOYMENT_SESSION="${TRADEMASTER_DEPLOYMENT_SESSION:-trademaster-deployments}"
SCHEDULER_SESSION="${TRADEMASTER_SCHEDULER_SESSION:-trademaster-scheduler}"
export TRADINGAGENTS_UI_DATABASE_URL="${TRADINGAGENTS_UI_DATABASE_URL:-sqlite:///${ROOT_DIR}/.tradingagents-ui.db}"
export TRADEMASTER_RESEARCH_ARTIFACTS="${TRADEMASTER_RESEARCH_ARTIFACTS:-${ROOT_DIR}/.research-artifacts}"
API_URL="http://127.0.0.1:${API_PORT}/api/health"
WEB_URL="http://127.0.0.1:${WEB_PORT}/"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required to run TradeMaster local services." >&2
  exit 1
fi

if [[ ! -x "${ROOT_DIR}/.venv/bin/uvicorn" ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "Missing ${ROOT_DIR}/.venv/bin/uvicorn and uv is not installed." >&2
    exit 1
  fi
  echo "Creating Python environment with uv sync --extra dev..."
  (cd "${ROOT_DIR}" && uv sync --extra dev)
fi

if [[ ! -d "${ROOT_DIR}/node_modules" ]]; then
  echo "Installing web dependencies with npm install..."
  (cd "${ROOT_DIR}" && npm install)
fi

if [[ "${TRADEMASTER_SKIP_WEB_BUILD:-0}" != "1" ]]; then
  echo "Creating Next.js production build..."
  (cd "${ROOT_DIR}" && npm run web:build)
elif [[ ! -d "${ROOT_DIR}/apps/web/.next" ]]; then
  echo "Creating Next.js production build..."
  (cd "${ROOT_DIR}" && npm run web:build)
fi

bash "${ROOT_DIR}/scripts/stop-local.sh"

printf -v api_command '%q ' env "TRADINGAGENTS_UI_DATABASE_URL=$TRADINGAGENTS_UI_DATABASE_URL" "TRADEMASTER_RESEARCH_ARTIFACTS=$TRADEMASTER_RESEARCH_ARTIFACTS" "${ROOT_DIR}/.venv/bin/uvicorn" tradingagents.ui.api:create_app --factory --host 127.0.0.1 --port "$API_PORT"
tmux new-session -d -s "$API_SESSION" -c "$ROOT_DIR" "$api_command"

tmux new-session -d -s "${WEB_SESSION}" \
  "cd '${ROOT_DIR}' && TRADEMASTER_API_BASE='http://127.0.0.1:${API_PORT}' NEXT_PUBLIC_API_BASE='http://127.0.0.1:${API_PORT}' npm --workspace apps/web run start -- --hostname 127.0.0.1 --port '${WEB_PORT}'"

wait_for_url() {
  local label="$1"
  local url="$2"
  local attempts=40

  for _ in $(seq 1 "${attempts}"); do
    if curl -fsS "${url}" >/dev/null 2>&1; then
      echo "${label}: ${url}"
      return 0
    fi
    sleep 0.25
  done

  echo "${label} did not become healthy: ${url}" >&2
  return 1
}

wait_for_url "API ready" "${API_URL}"
wait_for_url "Web ready" "${WEB_URL}"

echo "Sessions:"
echo "  ${API_SESSION} -> FastAPI on ${API_URL}"
echo "  ${WEB_SESSION} -> Next.js on ${WEB_URL}"

# Workers consume only explicitly queued research and reviewed deployments.
# The deployment worker cannot approve or submit an order.
start_worker() {
  local session="$1" module="$2" command log_path
  mkdir -p "${TRADEMASTER_RESEARCH_ARTIFACTS}/runtime-logs"
  printf -v log_path '%q' "${TRADEMASTER_RESEARCH_ARTIFACTS}/runtime-logs/${session}.log"
  printf -v command '%q ' "${ROOT_DIR}/.venv/bin/python" -u -m "$module" \
    --database-url "$TRADINGAGENTS_UI_DATABASE_URL" --artifacts "$TRADEMASTER_RESEARCH_ARTIFACTS"
  tmux new-session -d -s "$session" -c "$ROOT_DIR" "$command >> $log_path 2>&1"
}
start_worker "$RESEARCH_SESSION" tradingagents.research.worker
start_worker "$DEPLOYMENT_SESSION" tradingagents.research.deployment_worker
start_worker "$SCHEDULER_SESSION" tradingagents.scheduling.worker

# A process existing is not proof of readiness: require API-visible heartbeats.
"${ROOT_DIR}/.venv/bin/python" - "$API_PORT" <<'PYWORKERS'
import json, sys, time, urllib.request
for path, label, key, room in (("research", "Research", "available", "research"), ("research/deployments", "Deployment", "evaluation_worker_connected", "market"), ("execution-schedules", "Scheduler", "connected", "market")):
    url = f"http://127.0.0.1:{sys.argv[1]}/api/{path}/runtime"
    for attempt in range(40):
        try:
            request = urllib.request.Request(url, headers={"x-trademaster-room":room})
            with urllib.request.urlopen(request, timeout=2) as response:
                state = json.load(response)
            if state.get(key):
                print(f"{label} worker: heartbeat received")
                break
        except (OSError, ValueError):
            pass
        time.sleep(.5)
    else:
        raise SystemExit(f"{label} worker did not report ready; inspect its tmux session")
PYWORKERS
