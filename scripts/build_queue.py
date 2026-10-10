"""Build data/queue.json: demo alert queue with precomputed DALIL scores.

Run after training (scripts/train.py). Deterministic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.pipeline import analyze  # noqa: E402


def main() -> None:
    rows = []
    src = ROOT / "data/generated/cases_demo.jsonl"
    with src.open(encoding="utf-8") as f:
        cases = [json.loads(line) for line in f if line.strip()]
    for r in cases:
        res, _ = analyze(r, want_narrative=False)
        rows.append({
            "case_id": r["case_id"],
            "subject_name": r["subject_name"],
            "subject_kind": r["subject_kind"],
            "branch": r.get("branch", ""),
            "opened_at": r.get("opened_at", ""),
            "n_tx": len(r["transactions"]),
            "score": res.score,
            "risk_band": res.risk_band,
            "scenarios": [h.code for h in res.scenarios if h.matched],
            "labels": r["labels"],
            "is_suspicious": r["is_suspicious"],
        })
    rows.sort(key=lambda x: -x["score"])
    out = ROOT / "data/queue.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"queue: {len(rows)} cases -> {out}")


if __name__ == "__main__":
    main()
