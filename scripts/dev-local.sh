#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${TRADEMASTER_API_PORT:-8787}"
WEB_PORT="${TRADEMASTER_WEB_PORT:-3000}"
API_SESSION="${TRADEMASTER_API_SESSION:-trademaster-api}"
WEB_SESSION="${TRADEMASTER_WEB_SESSION:-wealth-agents-web}"
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

if [[ ! -d "${ROOT_DIR}/apps/web/.next" ]]; then
  echo "Creating Next.js production build..."
  (cd "${ROOT_DIR}" && npm run web:build)
fi

tmux kill-session -t "${API_SESSION}" 2>/dev/null || true
tmux kill-session -t "${WEB_SESSION}" 2>/dev/null || true

tmux new-session -d -s "${API_SESSION}" \
  "cd '${ROOT_DIR}' && .venv/bin/uvicorn tradingagents.ui.api:create_app --factory --host 0.0.0.0 --port '${API_PORT}'"

tmux new-session -d -s "${WEB_SESSION}" \
  "cd '${ROOT_DIR}' && NEXT_PUBLIC_API_BASE='http://127.0.0.1:${API_PORT}' npm --workspace apps/web run start -- --hostname 0.0.0.0 --port '${WEB_PORT}'"

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
