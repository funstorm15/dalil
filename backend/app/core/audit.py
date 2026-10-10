"""Append-only audit log of analyst decisions (JSONL on disk)."""
from __future__ import annotations

import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from .schemas import AuditEntry

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "audit" / "audit.log"
_MEM: deque[dict] = deque(maxlen=500)


def append(entry: AuditEntry, path: Path | None = None) -> AuditEntry:
    p = path or DEFAULT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    row = entry.model_dump()
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    _MEM.append(row)
    return entry


def record_decision(case_id: str, score: float, decision: str, analyst: str, note: str,
                    narrative_check: dict, model_version: str, path: Path | None = None) -> AuditEntry:
    entry = AuditEntry(
        ts=datetime.now(UTC).isoformat(),
        case_id=case_id,
        score=round(score, 1),
        decision=decision,
        analyst=analyst,
        note=note,
        narrative_check=narrative_check,
        model_version=model_version,
    )
    return append(entry, path)


def tail(limit: int = 50, path: Path | None = None) -> list[dict]:
    p = path or DEFAULT_PATH
    rows: list[dict] = []
    if p.exists():
        with p.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    if not rows:
        rows = [dict(r) for r in _MEM]
    return rows[-limit:][::-1]
