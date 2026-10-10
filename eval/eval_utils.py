"""Metric helpers shared by scripts/train.py and eval/run_eval.py."""
from __future__ import annotations

import math


def roc_auc(y: list[int], s: list[float]) -> float:
    pos = [x for x, y_ in zip(s, y, strict=False) if y_ == 1]
    neg = [x for x, y_ in zip(s, y, strict=False) if y_ == 0]
    if not pos or not neg:
        return float("nan")
    # Mann-Whitney U with tie handling
    sorted_all = sorted(zip(s, y, strict=False))
    rank_sum_pos, i = 0.0, 0
    n = len(sorted_all)
    while i < n:
        j = i
        while j < n and sorted_all[j][0] == sorted_all[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2  # 1-based average rank of tie group
        for k in range(i, j):
            if sorted_all[k][1] == 1:
                rank_sum_pos += avg_rank
        i = j
    n_pos, n_neg = len(pos), len(neg)
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def pr_auc(y: list[int], s: list[float]) -> float:
    pairs = sorted(zip(s, y, strict=False), key=lambda p: -p[0])
    tp = fp = 0
    prev_recall = 0.0
    ap = 0.0
    n_pos = sum(y)
    if n_pos == 0:
        return float("nan")
    for _, label in pairs:
        if label == 1:
            tp += 1
        else:
            fp += 1
        recall = tp / n_pos
        precision = tp / (tp + fp)
        ap += (recall - prev_recall) * precision
        prev_recall = recall
    return ap


def ece(y: list[int], p: list[float], bins: int = 10) -> float:
    """Expected calibration error."""
    if not y:
        return float("nan")
    buckets: list[list[tuple[int, float]]] = [[] for _ in range(bins)]
    for yi, pi in zip(y, p, strict=False):
        b = min(bins - 1, max(0, int(pi * bins)))
        buckets[b].append((yi, pi))
    err = 0.0
    for b in buckets:
        if not b:
            continue
        acc = sum(yi for yi, _ in b) / len(b)
        conf = sum(pi for _, pi in b) / len(b)
        err += len(b) / len(y) * abs(acc - conf)
    return err


def binary_metrics(y: list[int], s: list[float], threshold: float) -> dict:
    tp = sum(1 for yi, si in zip(y, s, strict=False) if yi == 1 and si >= threshold)
    fn = sum(1 for yi, si in zip(y, s, strict=False) if yi == 1 and si < threshold)
    fp = sum(1 for yi, si in zip(y, s, strict=False) if yi == 0 and si >= threshold)
    tn = sum(1 for yi, si in zip(y, s, strict=False) if yi == 0 and si < threshold)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {
        "threshold": round(threshold, 4),
        "n": len(y),
        "n_pos": sum(y),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "fpr": round(fpr, 4),
        "f1": round(f1, 4),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
    }


def precision_at_prevalence(precision_at_sample: float, recall: float, prev: float) -> float:
    """Re-base precision from the test-sample prevalence to an operational one."""
    if recall == 0:
        return 0.0
    # from sample: P = rec*prev_s / (rec*prev_s + fpr*(1-prev_s)); recover fpr
    return precision_at_sample  # placeholder — prevalence re-base done in run_eval


def fmt(x: float) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "n/a"
    return f"{x:.4f}"
