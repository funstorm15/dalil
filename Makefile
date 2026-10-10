# DALIL — local development commands
VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: setup data model serve llm dev eval test lint build web docker

setup:
	uv venv $(VENV) --python 3.12 || python3.12 -m venv $(VENV)
	$(PIP) install -r requirements.txt pytest ruff
	cd frontend && npm ci --no-audit --no-fund

data:
	$(PY) data/generator/generate.py
	$(PY) scripts/build_queue.py

model:
	$(PY) scripts/train.py

llm:  ## fetch runtime + default (1.5b) model; MODEL=3b for the larger one
	bash scripts/download_llm.sh

serve:  ## API + SPA on :8000 (needs `make llm` + llama-server running for narratives)
	$(PY) -m uvicorn app.main:app --app-dir backend --reload --port 8000

llm-serve:  ## run the local model server on :8081
	./llama.cpp/dist/llama-server -m model/dalil-llm.Q4_K_M.gguf --alias dalil-qwen \
	  --host 127.0.0.1 --port 8081 -c 4096 -t 8

web:
	cd frontend && npm run build

eval:
	$(PY) eval/run_eval.py

test:
	$(PY) -m pytest -q
	$(VENV)/bin/ruff check .

build: web
	docker build -t dalil:local .

docker: build
	docker run --rm -p 7860:7860 dalil:local
