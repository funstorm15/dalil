"""Server-side record of every analysis run.

Each /api/analyze call gets a fresh analysis_id. The server stores the exact
input it analysed, the input hash and the full result it computed; decisions
and exports reference that record by analysis_id — the browser never supplies
the score, evidence or note checks that end up in a decision or export.

Storage: one JSON file per analysis in config.ANALYSES_DIR (survives process
restarts on the same disk; a container needs a mounted volume for it).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .export import canonical_bytes

_ID_RE = re.compile(r"^an-[0-9a-f]{32}$")


def new_analysis_id() -> str:
    return f"an-{uuid.uuid4().hex}"


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def input_record(kind: str, payload: Any, amount_format: str | None = None) -> dict[str, Any]:
    rec: dict[str, Any] = {"kind": kind, "payload": payload}
    if amount_format:
        rec["amount_format"] = amount_format
    return rec


def save(directory: Path, analysis_id: str, inp: dict[str, Any], input_sha256: str,
         result: dict[str, Any]) -> dict[str, Any]:
    record = {
        "analysis_id": analysis_id,
        "created_at": datetime.now(UTC).isoformat(),
        "input": inp,
        "input_sha256": input_sha256,
        "result": result,
        "result_sha256": sha256_json(result),
    }
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"{analysis_id}.json"
    tmp = final.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, final)
    return record


def load(directory: Path, analysis_id: str) -> dict[str, Any] | None:
    if not isinstance(analysis_id, str) or not _ID_RE.match(analysis_id):
        return None
    p = directory / f"{analysis_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))
