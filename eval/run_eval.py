"""Full evaluation of the DALIL pipeline on held-out synthetic splits.

Outputs eval/results/eval_report.json consumed by the deck, README and the
System page of the demo. Includes: detection quality (model / rules /
ensemble), calibration, per-typology coverage, novel-variant generalization,
latency, narrative faithfulness (if the local LLM is up), operational cost
and concrete failure cases.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "backend"))

from app.core.features import extract_features  # noqa: E402
from app.core.ingest import normalize_case  # noqa: E402
from app.core.llm import LLMClient  # noqa: E402
from app.core.pipeline import analyze, rule_component  # noqa: E402
from app.core.riskmodel import predict_ml  # noqa: E402
from app.core.scenarios import run_scenarios  # noqa: E402
from eval_utils import ece, pr_auc, roc_auc  # noqa: E402

TYPOLOGIES = ["structuring", "pass_through", "mule_fanin", "crypto_offramp", "cycle_layering", "clean"]
BAND50 = 50.0  # escalation cut used by the product
PREVALENCE = 0.10  # assumed share of truly suspicious alerts in an operational queue


def load(split: str):
    path = ROOT / f"data/generated/cases_{split}.jsonl"
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def score_rows(rows, want_narrative: bool = False, sample_n: int | None = None):
    """Return (y, ml_p, ens_score, rule_flags, per-case meta)."""
    y, ml, ens, rule, meta = [], [], [], [], []
    for i, r in enumerate(rows):
        if sample_n is not None and i >= sample_n:
            break
        case = normalize_case(r)
        feats = extract_features(case)
        _, cal = predict_ml(feats)
        hits = run_scenarios(case)
        rc = rule_component(hits)
        rule_hit = 1 if any(h.matched for h in hits) else 0
        score = 100.0 * (0.7 * cal + 0.3 * rc)
        y.append(1 if case.is_suspicious else 0)
        ml.append(cal)
        ens.append(score)
        rule.append(rule_hit)
        meta.append({
            "case_id": case.case_id, "label": r["labels"][0],
            "ml": round(cal, 4), "score": round(score, 1),
            "rules": [h.code for h in hits if h.matched],
            "n_tx": len(case.transactions),
            "generator_variant": r.get("generator_variant", "base"),
        })
    return np.array(y), np.array(ml), np.array(ens), np.array(rule), meta


def detection_block(y, ml, ens, rule) -> dict:
    tnr = 1.0 - float(np.mean(rule[y == 0]))
    block = {
        "n": int(len(y)),
        "n_suspicious": int(y.sum()),
        "prevalence_in_sample": round(float(y.mean()), 3),
        "model_roc_auc": round(roc_auc(list(y), list(ml)), 4),
        "model_pr_auc": round(pr_auc(list(y), list(ml)), 4),
        "model_ece": round(ece(list(y), list(ml)), 4),
        "ensemble_roc_auc": round(roc_auc(list(y), list(ens)), 4),
        "at_band_50": {
            "model_at_prob_0_5": _bin(y, np.array([1 if m >= 0.5 else 0 for m in ml])),
            "rules": _bin(y, rule),
            "ensemble": _bin(y, (ens >= BAND50).astype(int)),
        },
    }
    # precision re-based to operational prevalence
    tp = int(((ens >= BAND50) & (y == 1)).sum())
    fp = int(((ens >= BAND50) & (y == 0)).sum())
    fn = int(((ens < BAND50) & (y == 1)).sum())
    tn = int(((ens < BAND50) & (y == 0)).sum())
    tpr = tp / (tp + fn) if tp + fn else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    prec_op = (tpr * PREVALENCE) / (tpr * PREVALENCE + fpr * (1 - PREVALENCE)) if (tpr + fpr) else 0.0
    block["ensemble_at_band50_precision_at_prevalence"] = {
        "prevalence": PREVALENCE,
        "precision": round(prec_op, 4),
        "recall": round(tpr, 4),
        "fpr": round(fpr, 4),
    }
    _ = tnr
    return block


def _bin(y, pred) -> dict:
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {
        "precision": round(prec, 4), "recall": round(rec, 4),
        "fpr": round(fp / (fp + tn), 4) if fp + tn else 0.0,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
    }


def per_typology(rows, rule, ens, y) -> dict:
    out = {}
    labs = [r["labels"][0] for r in rows]
    for lab in TYPOLOGIES:
        idx = [i for i, L in enumerate(labs) if L == lab]
        if not idx:
            continue
        if lab == "clean":
            out[lab] = {
                "n": len(idx),
                "rule_flag_rate": round(float(rule[idx].mean()), 3),
                "ensemble_flag_rate@50": round(float((ens[idx] >= BAND50).mean()), 3),
                "ensemble_mean_score": round(float(ens[idx].mean()), 1),
            }
        else:
            out[lab] = {
                "n": len(idx),
                "rule_recall": round(float(rule[idx].mean()), 3),
                "ensemble_recall@50": round(float((ens[idx] >= BAND50).mean()), 3),
                "ensemble_mean_score": round(float(ens[idx].mean()), 1),
            }
    _ = y
    return out


def latency_block() -> dict:
    rows = load("demo")[:60]
    durs = []
    stage_acc: dict[str, list[float]] = {}
    for r in rows:
        t0 = time.perf_counter()
        res, _ = analyze(r, want_narrative=False)
        durs.append((time.perf_counter() - t0) * 1000)
        for t in res.timings:
            stage_acc.setdefault(t.stage, []).append(t.ms)
    return {
        "pipeline_no_llm_ms": {
            "p50": round(statistics.median(durs), 1),
            "p95": round(sorted(durs)[int(len(durs) * 0.95) - 1], 1),
            "max": round(max(durs), 1),
            "n": len(durs),
        },
        "stage_p50_ms": {k: round(statistics.median(v), 2) for k, v in stage_acc.items()},
    }


def narrative_block(llm: LLMClient, sample_n: int = 20) -> dict:
    rows = load("test")
    step = max(1, len(rows) // sample_n)
    sample = rows[::step][:sample_n]
    precisions, invalid, unver = [], 0, 0
    tokens_prompt, tokens_completion = [], []
    lat = []
    mode = "deterministic"
    health = llm.health(timeout=3.0)
    for r in sample:
        res, _ = analyze(r, llm=llm, want_narrative=True)
        precisions.append(res.narrative_check.citation_precision)
        invalid += len(res.narrative_check.invalid_citations)
        unver += len(res.narrative_check.unverified_numbers)
        st = res.input_summary.get("llm") or {}
        if st.get("available"):
            mode = "llm"
            lat.append(st.get("latency_ms", 0))
            if st.get("prompt_tokens"):
                tokens_prompt.append(st["prompt_tokens"])
            if st.get("completion_tokens"):
                tokens_completion.append(st["completion_tokens"])
    block = {
        "mode": mode,
        "llm_available": health.available,
        "llm_model": llm.model,
        "sample_n": len(sample),
        "mean_citation_precision": round(sum(precisions) / len(precisions), 4) if precisions else None,
        "invalid_citations_total": invalid,
        "unverified_numbers_total": unver,
    }
    if lat:
        block["llm_latency_ms"] = {"p50": round(statistics.median(lat), 0), "n": len(lat)}
        block["avg_tokens"] = {
            "prompt": int(statistics.mean(tokens_prompt)) if tokens_prompt else None,
            "completion": int(statistics.mean(tokens_completion)) if tokens_completion else None,
        }
    return block


def failure_cases(ml, ens, y, meta, limit: int = 6) -> dict:
    fps, fns = [], []
    for i, m in enumerate(meta):
        flag = ens[i] >= BAND50
        if y[i] == 0 and flag:
            fps.append(m)
        if y[i] == 1 and not flag:
            fns.append(m)
    return {
        "false_positives_at_50": sorted(fps, key=lambda m: -m["score"])[:limit],
        "false_negatives_at_50": sorted(fns, key=lambda m: m["score"])[:limit],
        "fp_count": len(fps),
        "fn_count": len(fns),
    }


def main() -> None:
    llm = LLMClient()
    report: dict = {"generated_by": "eval/run_eval.py"}

    rows_test = load("test")
    y, ml, ens, rule, meta = score_rows(rows_test)
    report["test"] = detection_block(y, ml, ens, rule)
    report["test"]["per_typology"] = per_typology(rows_test, rule, ens, y)

    rows_novel = load("novel")
    y2, ml2, ens2, rule2, meta2 = score_rows(rows_novel)
    report["novel_variants"] = detection_block(y2, ml2, ens2, rule2)
    report["novel_variants"]["per_typology"] = per_typology(rows_novel, rule2, ens2, y2)
    report["generalization"] = {
        "note": ("novel split holds typology variants never seen in training "
                 "(different thresholds, delays, sender reuse)"),
        "model_auc_test": report["test"]["model_roc_auc"],
        "model_auc_novel": report["novel_variants"]["model_roc_auc"],
        "ensemble_recall_test": report["test"]["at_band_50"]["ensemble"]["recall"],
        "ensemble_recall_novel": report["novel_variants"]["at_band_50"]["ensemble"]["recall"],
        "rules_recall_test": report["test"]["at_band_50"]["rules"]["recall"],
        "rules_recall_novel": report["novel_variants"]["at_band_50"]["rules"]["recall"],
    }

    report["latency"] = latency_block()
    report["narrative"] = narrative_block(llm)
    report["failures"] = failure_cases(ml, ens, y, meta)

    out = ROOT / "eval/results/eval_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("test", "generalization", "latency", "narrative")},
                     indent=2)[:4000])
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
