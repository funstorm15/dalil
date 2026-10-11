#!/usr/bin/env bash
# Explicitly promote V2 to the existing public demo; V1 files stay intact.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
V2_ROOT="$PWD"
mkdir -p "$V2_ROOT/work/deployment"
exec > >(tee -a "$V2_ROOT/work/deployment/activation.log") 2>&1
trap 'code=$?; echo "Activation stopped at line $LINENO (exit $code). V1 has not been switched unless reported below." >&2; exit "$code"' ERR
echo "Starting DALIL V2 activation: $(date -Is)"
echo "Checking prerequisites…"
PUBLIC_URL="https://cornbread-left-licking.ngrok-free.dev"
if [ ! -f "$V2_ROOT/frontend/dist/index.html" ]; then
  echo "V2 frontend build is missing. Run: npm run build --prefix $V2_ROOT/frontend" >&2; exit 1
fi
echo "Checking the existing ngrok agent…"
curl -fsS http://127.0.0.1:4040/api/endpoints >/dev/null

wait_http() {
  local endpoint="$1"
  for attempt in $(seq 1 60); do
    if curl -fsS --max-time 2 "$endpoint" >/dev/null 2>&1; then return 0; fi
    if (( attempt % 10 == 0 )); then echo "Waiting for $endpoint ($attempt/60)…"; fi
    sleep 1
  done
  echo "Endpoint did not become ready: $endpoint" >&2
  journalctl --user -u dalil-v2-api -u dalil-v2-llama -n 20 --no-pager || true
  return 1
}

echo "Starting V2 language model…"
if ! curl -fsS --max-time 2 http://127.0.0.1:18081/health >/dev/null 2>&1; then
  systemctl --user reset-failed dalil-v2-llama 2>/dev/null || true
  systemd-run --user --unit=dalil-v2-llama --property=Restart=always \
    --property=WorkingDirectory="$V2_ROOT" \
    "$V2_ROOT/llama.cpp/dist/llama-server" \
    -m "$V2_ROOT/model/dalil-llm.Q4_K_M.gguf" --alias dalil-qwen \
    --host 127.0.0.1 --port 18081 -c 4096 -t 4 -fa on
fi
wait_http http://127.0.0.1:18081/health
echo "Starting V2 application…"
if ! systemctl --user is-active --quiet dalil-v2-api; then
  systemctl --user reset-failed dalil-v2-api 2>/dev/null || true
  systemd-run --user --unit=dalil-v2-api --property=Restart=always \
    --property=WorkingDirectory="$V2_ROOT" --setenv=DALIL_V2_PORT=8013 \
    /usr/bin/bash "$V2_ROOT/scripts/run_demo.sh"
fi
wait_http http://127.0.0.1:8013/api/health

echo "Switching the existing tunnel to V2…"
"$V2_ROOT/.venv/bin/python" "$V2_ROOT/scripts/switch_endpoint.py" --port 8013
trap - ERR
echo "V2 is live at $PUBLIC_URL. V1 files are unchanged."
echo 'Unmanaged V1 processes are left running locally; they no longer serve this URL.'
echo 'Rerun this script if the existing ngrok agent is restarted.'
