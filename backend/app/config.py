"""Application configuration (env-driven, no secrets required)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:18081/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "dalil-qwen")
GENERATED_DIR = Path(os.environ.get("GENERATED_DIR", ROOT / "data/generated"))
QUEUE_PATH = Path(os.environ.get("QUEUE_PATH", ROOT / "data/queue.json"))
AUDIT_PATH = Path(os.environ.get("AUDIT_PATH", ROOT / "data/audit/audit.log"))
# one JSON file per analysis run (server-side source of truth for decisions/exports)
ANALYSES_DIR = Path(os.environ.get("ANALYSES_DIR", ROOT / "data/analyses"))
RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", ROOT / "eval/results"))
STATIC_DIR = Path(os.environ.get("STATIC_DIR", ROOT / "frontend/dist"))
MAX_CSV_BYTES = int(os.environ.get("MAX_CSV_BYTES", 2_000_000))
