"""Train the DALIL risk model on the synthetic casebook.

Produces:
  model/dalil_model.joblib         {model, calibrator, feature_keys, ...}
  eval/results/train_report.json   train/val quality + operating threshold

Deterministic given the seed (fixed split indices, fixed generator seed).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "backend"))

from app.core.features import FEATURE_KEYS, extract_features, vector  # noqa: E402
from app.core.ingest import normalize_case  # noqa: E402
from eval_utils import ece, pr_auc, roc_auc  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sklearn.isotonic import IsotonicRegression  # noqa: E402

SEED = 20261010
VERSION = "dalil-gbm-1.0.0"
TARGET_FPR = 0.15  # operating point: at most 15% of clean alerts escalated


def load_xy(path: Path) -> tuple[np.ndarray, np.ndarray, list[str]]:
    xs, ys, ids = [], [], []
    with path.open(encoding="utf-8") as f:
        for line in f:
            raw = json.loads(line)
            case = normalize_case(raw)
            xs.append(vector(extract_features(case)))
            ys.append(1 if case.is_suspicious else 0)
            ids.append(case.case_id)
    return np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.int64), ids


def find_threshold(y: np.ndarray, p: np.ndarray, target_fpr: float) -> float:
    """Highest recall threshold whose FPR stays ≤ target."""
    candidates = np.unique(p)
    best_t, best_rec = 0.5, -1.0
    for t in candidates:
        pred = p >= t
        neg = y == 0
        fpr = float(np.mean(pred[neg])) if neg.sum() else 1.0
        if fpr <= target_fpr:
            rec = float(np.mean(pred[y == 1]))
            if rec > best_rec:
                best_rec, best_t = rec, float(t)
    return best_t


def main() -> None:
    train_path = ROOT / "data/generated/cases_train.jsonl"
    t0 = time.time()
    X, y, _ = load_xy(train_path)
    rng = np.random.default_rng(SEED)
    idx = rng.permutation(len(y))
    cut = int(len(y) * 0.8)
    tr, va = idx[:cut], idx[cut:]
    X_tr, y_tr, X_va, y_va = X[tr], y[tr], X[va], y[va]

    clf = HistGradientBoostingClassifier(
        max_iter=260, learning_rate=0.07, max_leaf_nodes=31,
        min_samples_leaf=25, l2_regularization=1.0, random_state=SEED,
    )
    clf.fit(X_tr, y_tr)

    p_va_raw = clf.predict_proba(X_va)[:, 1]
    iso = IsotonicRegression(y_min=0.001, y_max=0.999, out_of_bounds="clip")
    iso.fit(p_va_raw, y_va)
    p_va = iso.predict(p_va_raw)

    thr = find_threshold(y_va, p_va, TARGET_FPR)
    report = {
        "version": VERSION,
        "trained_at": datetime.now(UTC).isoformat(),
        "train_n": int(len(y_tr)),
        "val_n": int(len(y_va)),
        "val_pos_rate": float(y.mean()),
        "val_roc_auc": round(roc_auc(list(y_va), list(p_va)), 4),
        "val_pr_auc": round(pr_auc(list(y_va), list(p_va)), 4),
        "val_ece": round(ece(list(y_va), list(p_va)), 4),
        "operating_threshold": round(thr, 4),
        "target_fpr": TARGET_FPR,
        "feature_count": len(FEATURE_KEYS),
        "train_seconds": round(time.time() - t0, 1),
    }

    bundle = {
        "model": clf,
        "calibrator": iso,
        "feature_keys": FEATURE_KEYS,
        "version": VERSION,
        "threshold": thr,
        "params": {"max_iter": 260, "learning_rate": 0.07, "seed": SEED},
        "report": report,
        "medians": {k: float(np.median(X[:, i])) for i, k in enumerate(FEATURE_KEYS)},
    }
    (ROOT / "model").mkdir(exist_ok=True)
    joblib.dump(bundle, ROOT / "model/dalil_model.joblib")
    out_dir = ROOT / "eval/results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "train_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
