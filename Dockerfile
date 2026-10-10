# DALIL — container image: local LLM + API + SPA. Zero egress at runtime.
# Stage 1: build the SPA so deployment is fully "from the submitted repo".
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: runtime
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    LLM_BASE_URL=http://127.0.0.1:8081/v1 \
    LLM_MODEL=dalil-qwen \
    LLM_THREADS=2

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tar gzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ backend/
COPY --from=web /web/dist/ frontend/dist/
COPY data/generated/ data/generated/
COPY data/queue.json data/queue.json
COPY model/dalil_model.joblib model/dalil_model.joblib
COPY eval/results/ eval/results/
COPY scripts/ scripts/
RUN chmod +x scripts/download_llm.sh scripts/entrypoint.sh

# inference runtime + open-weight model (weights downloaded once at build)
RUN bash scripts/download_llm.sh

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 \
  CMD curl -fsS http://127.0.0.1:${PORT}/api/health || exit 1

CMD ["bash", "scripts/entrypoint.sh"]
