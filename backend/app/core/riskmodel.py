"""Risk model bundle loading, prediction and per-feature attribution."""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np

from .features import FEATURE_KEYS, vector

_BUNDLE: dict | None = None


def load_bundle(path: Path | None = None) -> dict:
    global _BUNDLE
    if _BUNDLE is None:
        p = path or Path(__file__).resolve().parents[3] / "model/dalil_model.joblib"
        _BUNDLE = joblib.load(p)
    return _BUNDLE


def predict_ml(features: dict[str, float]) -> tuple[float, float]:
    """Return (raw_prob, calibrated_prob)."""
    b = load_bundle()
    x = np.asarray([vector(features)], dtype=np.float64)
    raw = float(b["model"].predict_proba(x)[0, 1])
    cal = float(np.clip(b["calibrator"].predict([raw])[0], 0.0, 1.0))
    return raw, cal


def feature_contributions(features: dict[str, float], baseline: dict[str, float] | None = None,
                          top_n: int = 6) -> list[dict]:
    """Leave-one-feature-out attribution against a baseline (train median).

    Honest and model-agnostic: replacing one input with its typical value and
    re-predicting shows how much that fact moved THIS case's score.
    """
    b = load_bundle()
    base = baseline or b.get("medians") or {k: 0.0 for k in FEATURE_KEYS}
    x = np.asarray([vector(features)], dtype=np.float64)
    raw0 = float(b["model"].predict_proba(x)[0, 1])
    rows = []
    xb = x.copy()
    for i, k in enumerate(FEATURE_KEYS):
        xb[0, i] = base.get(k, 0.0)
        raw1 = float(b["model"].predict_proba(xb)[0, 1])
        xb[0, i] = x[0, i]
        rows.append({"feature": k, "value": float(x[0, i]), "baseline": float(base.get(k, 0.0)),
                     "impact": round((raw0 - raw1) * 100.0, 2)})
    rows.sort(key=lambda r: -abs(r["impact"]))
    return rows[:top_n]
