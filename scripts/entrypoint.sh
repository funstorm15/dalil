#!/usr/bin/env bash
# Container entrypoint: local LLM first, then the API serving the SPA.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-7860}"
LLM_GGUF="${LLM_GGUF:-model/dalil-llm.Q4_K_M.gguf}"
LLM_PORT=8081

if [ -x "llama.cpp/dist/llama-server" ] && [ -f "$LLM_GGUF" ]; then
  echo "[entrypoint] starting llama-server on :${LLM_PORT} (model=$LLM_GGUF, threads=${LLM_THREADS:-2})"
  llama.cpp/dist/llama-server \
    -m "$LLM_GGUF" \
    --alias "${LLM_MODEL:-dalil-qwen}" \
    --host 127.0.0.1 --port "$LLM_PORT" \
    -c 4096 -t "${LLM_THREADS:-2}" \
    > /tmp/llama-server.log 2>&1 &
  LLM_PID=$!
  for i in $(seq 1 60); do
    if curl -fsS --max-time 2 "http://127.0.0.1:${LLM_PORT}/health" >/dev/null 2>&1; then
      echo "[entrypoint] llama-server ready (${i}s)"
      break
    fi
    sleep 1
  done
else
  echo "[entrypoint] LLM runtime/model missing — running in deterministic narrative mode"
fi

exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --app-dir backend --log-level warning
