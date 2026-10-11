#!/usr/bin/env bash
# V2 is local-only. Never starts/stops V1 services or changes an ngrok tunnel.
set -euo pipefail
cd "$(dirname "$0")/.."
DALIL_V2_ROOT="$PWD"
mkdir -p "$DALIL_V2_ROOT/data/analyses" "$DALIL_V2_ROOT/data/audit"
export AUDIT_PATH="$DALIL_V2_ROOT/data/audit/audit.log"
export ANALYSES_DIR="$DALIL_V2_ROOT/data/analyses"
export GENERATED_DIR="$DALIL_V2_ROOT/data/generated"
export QUEUE_PATH="$DALIL_V2_ROOT/data/queue.json"
export RESULTS_DIR="$DALIL_V2_ROOT/eval/results"
export STATIC_DIR="$DALIL_V2_ROOT/frontend/dist"
export LLM_BASE_URL="http://127.0.0.1:18081/v1"
export OMP_NUM_THREADS=1
exec "$DALIL_V2_ROOT/.venv/bin/python" -m uvicorn app.main:app --app-dir "$DALIL_V2_ROOT/backend" --host 127.0.0.1 --port "${DALIL_V2_PORT:-8012}"
