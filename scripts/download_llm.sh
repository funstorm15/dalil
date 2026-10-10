#!/usr/bin/env bash
# Fetch the local inference runtime + open-weight model used by the prototype.
#   - llama.cpp prebuilt server binary (MIT) from GitHub releases (pinned build)
#   - Qwen2.5-Instruct Q4_K_M GGUF (Apache-2.0) from Hugging Face
# Usage: MODEL=1.5b|3b bash scripts/download_llm.sh
set -uo pipefail
cd "$(dirname "$0")/.."

LLAMA_BUILD="${LLAMA_BUILD:-b11541}"
LLAMA_DIR="llama.cpp"
DIST="$LLAMA_DIR/dist"
MODEL="${MODEL:-1.5b}"
GGUF="model/dalil-llm.Q4_K_M.gguf"

case "$MODEL" in
  1.5b) GGUF_URL="${GGUF_URL:-https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf}" ;;
  3b)   GGUF_URL="${GGUF_URL:-https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf}" ;;
  *)    echo "[download] unknown MODEL=$MODEL (use 1.5b or 3b)" >&2; exit 1 ;;
esac

mkdir -p "$LLAMA_DIR/bin" model

if [ ! -x "$DIST/llama-server" ]; then
  echo "[download] llama.cpp ${LLAMA_BUILD} (ubuntu x64)..."
  ASSET="https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_BUILD}/llama-${LLAMA_BUILD}-bin-ubuntu-x64.tar.gz"
  if curl -fL --retry 3 "$ASSET" -o /tmp/llama-bin.tar.gz; then
    mkdir -p "$DIST"
    tar -xzf /tmp/llama-bin.tar.gz -C "$DIST" --strip-components=1
    if [ -x "$DIST/llama-server" ]; then
      echo "$LLAMA_BUILD" > "$LLAMA_DIR/BUILD"
      rm -f /tmp/llama-bin.tar.gz
    else
      echo "[download] llama-server not found in archive" >&2; exit 1
    fi
  else
    echo "[download] asset download failed: $ASSET" >&2; exit 1
  fi
fi

if [ ! -f "$GGUF" ]; then
  SIZE=$(curl -sIL "$GGUF_URL" | tr -d '\r' | awk 'tolower($1)=="content-length:"{print $2}' | tail -1)
  echo "[download] GGUF model (${SIZE:-~1 GB}, MODEL=$MODEL)..."
  curl -fL --retry 3 -o "$GGUF.part" "$GGUF_URL" || exit 1
  mv "$GGUF.part" "$GGUF"
fi

echo "[ok] llama-server: $(stat -c%s "$DIST/llama-server") bytes"
echo "[ok] gguf: $(stat -c%s "$GGUF") bytes"
