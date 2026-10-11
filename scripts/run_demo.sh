#!/usr/bin/env bash
# Demo stack: local LLM + API + ngrok tunnel as *transient* systemd user units.
#   start:  bash scripts/run_demo.sh            (idempotent: running parts are reused)
#   reload API after a code change:  RESTART_API=1 bash scripts/run_demo.sh
#   stop:   systemctl --user stop dalil-llama dalil-api dalil-ngrok
# Transient units restart on crash (Restart=always) but do NOT survive a reboot or
# logout — run this script again after the machine restarts.
# Env: PORT (default 8002), LLM_THREADS (default 4), NGROK_BIN, NGROK_AUTHTOKEN (once).
# The API runs with OMP_NUM_THREADS=1: single-case model calls are ~4x faster without
# OpenMP thread fan-out on this laptop (measured 11 Oct).
# Data: decisions -> data/audit/audit.log, analyses -> data/analyses/ (on this disk).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
PORT="${PORT:-8002}"
LOGDIR="${LOGDIR:-/tmp/dalil-demo}"
mkdir -p "$LOGDIR" "$ROOT/data/audit" "$ROOT/data/analyses"
systemctl --user reset-failed dalil-llama dalil-api dalil-ngrok 2>/dev/null || true

if [ -z "${NGROK_AUTHTOKEN:-}" ] && ! grep -q "authtoken:" ~/.config/ngrok/ngrok.yml 2>/dev/null; then
  echo "ngrok authtoken missing — run: ngrok config add-authtoken <token>" >&2
  exit 1
fi

# --- llama.cpp server ---
if curl -fsS --max-time 2 http://127.0.0.1:8081/health >/dev/null 2>&1; then
  echo "[demo] llama-server already up"
else
  systemd-run --user --unit=dalil-llama --property=Restart=always --property=RestartSec=2 \
    --property=WorkingDirectory="$ROOT" \
    "$ROOT/llama.cpp/dist/llama-server" \
    -m "$ROOT/model/dalil-llm.Q4_K_M.gguf" --alias dalil-qwen \
    --host 127.0.0.1 --port 8081 -c 4096 -t "${LLM_THREADS:-4}" -fa on \
    > "$LOGDIR/llama.log" 2>&1
  echo "[demo] llama-server starting (unit dalil-llama)"
fi

# --- API ---
if [ "${RESTART_API:-0}" = 1 ]; then
  systemctl --user stop dalil-api 2>/dev/null || true
  systemctl --user reset-failed dalil-api 2>/dev/null || true
  sleep 1
fi
if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
  echo "[demo] API already up on :${PORT}"
else
  # bound to localhost only: the ngrok agent connects locally
  systemd-run --user --unit=dalil-api --property=Restart=always --property=RestartSec=2 \
    --property=WorkingDirectory="$ROOT" \
    --setenv=AUDIT_PATH="$ROOT/data/audit/audit.log" --setenv=ANALYSES_DIR="$ROOT/data/analyses" \
    --setenv=OMP_NUM_THREADS=1 \
    "$ROOT/.venv/bin/python" -m uvicorn app.main:app \
    --app-dir "$ROOT/backend" --host 127.0.0.1 --port "$PORT" \
    > "$LOGDIR/api.log" 2>&1
  echo "[demo] API starting (unit dalil-api)"
fi

# wait for both
for i in $(seq 1 60); do
  ok=1
  curl -fsS --max-time 2 http://127.0.0.1:8081/health >/dev/null 2>&1 || ok=0
  curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1 || ok=0
  [ "$ok" = 1 ] && break
  sleep 1
done
curl -fsS --max-time 3 http://127.0.0.1:8081/health >/dev/null || { echo "[demo] llama-server failed: see $LOGDIR/llama.log" >&2; exit 1; }
curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/api/health" >/dev/null || { echo "[demo] API failed: see $LOGDIR/api.log" >&2; exit 1; }
LLM_OK=$(curl -fsS "http://127.0.0.1:${PORT}/api/health" | "$ROOT/.venv/bin/python" -c 'import json,sys; print(json.load(sys.stdin)["llm"]["available"])')
echo "[demo] stack ready (narrative LLM available: $LLM_OK)"

# --- ngrok tunnel ---
systemctl --user stop dalil-ngrok 2>/dev/null || true
NGROK="${NGROK_BIN:-$(command -v ngrok || echo "$HOME/.local/share/dalil/ngrok")}"
[ -x "$NGROK" ] || { echo "[demo] ngrok binary not found — install it or set NGROK_BIN" >&2; exit 1; }
systemd-run --user --unit=dalil-ngrok --property=Restart=always --property=RestartSec=2 \
  "$NGROK" http "$PORT" --log "$LOGDIR/ngrok.log" > /dev/null
echo "[demo] tunnel starting (unit dalil-ngrok)"

URL=""
for i in $(seq 1 30); do
  URL=$("$ROOT/.venv/bin/python" - <<'PY' 2>/dev/null || true
import json, urllib.request
try:
    d = json.load(urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=3))
    print(next(t["public_url"] for t in d["tunnels"] if t["public_url"].startswith("https")))
except Exception:
    pass
PY
)
  [ -n "$URL" ] && break
  sleep 1
done
if [ -n "$URL" ]; then
  echo "[demo] PUBLIC URL: $URL"
  echo "[demo] first browser visit shows ngrok's interstitial — click 'Visit Site'"
else
  echo "[demo] tunnel URL not found — see $LOGDIR/ngrok.log" >&2
  exit 1
fi
