"""End-to-end analysis pipeline with stage timings and live events.

Stages (each timed, each streamed to the UI):
  ingest -> entities -> features -> scenarios -> model -> score
  -> evidence -> narrative -> verify

Deterministic stages run in milliseconds; the narrative stage is the only
LLM call and the only stage that can be offline (then a deterministic
extractive narrative is generated and labelled as such).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from .features import build_entity_clusters, extract_features
from .ingest import normalize_case
from .llm import SYSTEM_PROMPT, LLMClient, LLMUnavailable, build_user_prompt
from .riskmodel import feature_contributions, load_bundle, predict_ml
from .scenarios import run_scenarios
from .schemas import AnalysisResult, EvidenceItem, ScenarioHit, StageTiming, Transaction
from .verifier import verify_narrative

BUNDLE = None

RULE_WEIGHT = 0.30
ML_WEIGHT = 0.70

FEATURE_UNITS = {
    "total_in": " UZS", "total_out": " UZS", "net_flow": " UZS",
    "avg_in": " UZS", "avg_out": " UZS", "max_in": " UZS", "max_out": " UZS",
    "median_amount": " UZS", "declared_turnover_monthly": " UZS/mo",
    "end_balance": " UZS", "min_day_balance": " UZS",
    "account_age_days": " days", "span_days": " days",
}


def _bundle():
    global BUNDLE
    if BUNDLE is None:
        BUNDLE = load_bundle()
    return BUNDLE


def fmt_feature(key: str, value: float) -> str:
    unit = FEATURE_UNITS.get(key, "")
    if unit == " UZS" or unit == " UZS/mo":
        return f"{value / 1_000_000:,.1f} mln{unit}"
    if abs(value) >= 100:
        return f"{value:,.0f}{unit}"
    return f"{value:.2f}{unit}"


def rule_component(hits: list[ScenarioHit]) -> float:
    sev = sum(h.severity for h in hits if h.matched)
    return min(1.0, sev * 0.45)


def band(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


def decision_hint(score: float) -> str:
    if score >= 75:
        return "Escalate to L2 and prepare STR draft"
    if score >= 50:
        return "Escalate for enhanced review"
    if score >= 25:
        return "Request additional information / monitor"
    return "Dismiss with documented rationale"


def build_evidence(case, features: dict[str, float], hits: list[ScenarioHit],
                   top_features: list[dict]) -> list[EvidenceItem]:
    ev: list[EvidenceItem] = []
    n = 0

    def add(kind: str, text: str, ref: str = "") -> str:
        nonlocal n
        n += 1
        eid = f"E{n}"
        ev.append(EvidenceItem(id=eid, kind=kind, text=text, ref=ref))
        return eid

    add("subject",
        f"Subject: {case.subject_name} ({case.subject_kind}, account age "
        f"{case.account_age_days} d, declared turnover "
        f"{case.declared_turnover_monthly / 1e6:.0f} mln UZS/month, branch {case.branch or 'n/a'})",
        case.subject_account)
    for tf in top_features[:4]:
        add("feature", f"{tf['feature']} = {fmt_feature(tf['feature'], tf['value'])} "
                       f"(score impact {tf['impact']:+.1f} pp)", tf["feature"])
    for h in hits:
        if h.matched:
            add("scenario", f"{h.code} {h.name}: {h.detail}", h.code)

    # notable transactions: biggest in/out + scenario-referenced
    tx_by_id = {t.id: t for t in case.transactions}
    cited: set[str] = set()
    for h in hits:
        for tid in h.evidence:
            if tid in tx_by_id and tid not in cited:
                cited.add(tid)
                t = tx_by_id[tid]
                add("transaction", _tx_text(t), t.id)
                if len(cited) >= 5:
                    break
        if len(cited) >= 5:
            break
    if len(cited) < 3:
        for t in sorted(case.transactions, key=lambda x: -x.amount)[:4]:
            if t.id not in cited:
                add("transaction", _tx_text(t), t.id)
                cited.add(t.id)
    return ev


def _tx_text(t: Transaction) -> str:
    cp_name = t.to_name if t.direction == "in" else t.from_name
    side = "from" if t.direction == "in" else "to"
    memo = f", memo='{t.memo}'" if t.memo else ""
    return (f"tx {t.id} {t.ts} {t.direction} {t.amount / 1e6:.1f} mln UZS "
            f"{side} {cp_name} via {t.channel}{memo}")


def deterministic_narrative(case, hits: list[ScenarioHit], evidence: list[EvidenceItem],
                            score: float) -> str:
    matched = [h for h in hits if h.matched]
    lines = ["**1) SUMMARY** (deterministic extract — LLM offline)",
             f"Case {case.case_id}: DALIL score {score:.0f}/100 ({band(score)}) over "
             f"{len(case.transactions)} transactions; "
             f"{len(matched)} of {len(hits)} typology rules matched [E1].", ""]
    lines.append("**2) TYPOLOGY**")
    sc_ev = {e.ref: e.id for e in evidence if e.kind == "scenario"}
    if matched:
        for h in matched:
            cid = sc_ev.get(h.code, "E1")
            lines.append(f"- {h.code} {h.name}: {h.detail} [{cid}]")
    else:
        lines.append("No rule fully matched; score is driven by behavioural features [E1].")
    lines += ["", "**3) KEY EVIDENCE**"]
    for e in evidence[1:6]:
        lines.append(f"- {e.text} [{e.id}]")
    lines += ["", "**4) NEXT STEPS**",
              f"- {'Escalate to L2' if score >= 50 else 'Document dismissal rationale'} and "
              f"verify counterparty identity manually [E1]",
              "- Compare with prior 12-month history and KYC file (outside this prototype)."]
    return "\n".join(lines)


def analyze(raw: dict, llm: LLMClient | None = None, want_narrative: bool = True,
            emit: Callable[[dict], None] | None = None) -> tuple[AnalysisResult, list[dict]]:
    timings: list[StageTiming] = []
    events: list[dict] = []

    def stage(name: str, detail: str = ""):
        class _S:
            def __enter__(self):
                self.t0 = time.perf_counter()
                ev = {"stage": name, "status": "running", "detail": detail, "ms": 0.0}
                events.append(ev)
                if emit:
                    emit(ev)
                return self

            def __exit__(self, *a):
                ms = (time.perf_counter() - self.t0) * 1000
                timings.append(StageTiming(stage=name, ms=round(ms, 2)))
                ev = events[-1]
                ev.update(status="done", ms=round(ms, 2))
                if emit:
                    emit(ev)
                return False

        return _S()

    t_start = time.perf_counter()

    with stage("ingest"):
        case = normalize_case(raw)
    with stage("entities"):
        clusters = build_entity_clusters(case)
        merged = {}
        for k, cid in clusters.items():
            merged.setdefault(cid, []).append(k)
        merged_groups = [v for v in merged.values() if len(v) > 1]
    with stage("features"):
        features = extract_features(case)
    with stage("scenarios"):
        hits = run_scenarios(case)
    with stage("model"):
        raw_p, cal_p = predict_ml(features)
        top = feature_contributions(features)
    with stage("score"):
        rc = rule_component(hits)
        score = 100.0 * (ML_WEIGHT * cal_p + RULE_WEIGHT * rc)

    evidence = build_evidence(case, features, hits, top)

    with stage("narrative"):
        narrative = ""
        mode = "deterministic"
        llm_stats = None
        if want_narrative:
            case_brief = (
                f"case_id={case.case_id}; subject={case.subject_name} "
                f"({case.subject_kind}); window={len(case.transactions)} txs; "
                f"DALIL score={score:.0f}/100 ({band(score)}); "
                f"ML probability={cal_p:.2f}; rule component={rc:.2f}; "
                f"account_age={case.account_age_days}d."
            )
            ev_lines = [f"[{e.id}] ({e.kind}) {e.text}" for e in evidence]
            client = llm or LLMClient()
            try:
                narrative = client.chat(SYSTEM_PROMPT, build_user_prompt(case_brief, ev_lines))
                mode = "llm"
                llm_stats = client.last_stats
            except LLMUnavailable as e:
                narrative = deterministic_narrative(case, hits, evidence, score)
                llm_stats = client.last_stats
                events[-1]["detail"] = f"LLM unavailable ({e}); deterministic fallback used"
        else:
            narrative = deterministic_narrative(case, hits, evidence, score)
            events[-1]["detail"] = "narrative skipped (evaluation mode)"

    with stage("verify"):
        check = verify_narrative(narrative, evidence)
        check.mode = mode  # type: ignore[assignment]

    total_ms = (time.perf_counter() - t_start) * 1000
    top_features = [
        {"feature": t["feature"], "value": t["value"], "display": fmt_feature(t["feature"], t["value"]),
         "impact": t["impact"], "baseline": t["baseline"]}
        for t in top
    ]
    result = AnalysisResult(
        case_id=case.case_id,
        score=round(score, 1),
        risk_band=band(score),  # type: ignore[arg-type]
        decision_hint=decision_hint(score),
        suspicious=score >= 50,
        features={k: round(v, 4) for k, v in features.items()},
        top_features=top_features,
        scenarios=hits,
        evidence=evidence,
        narrative=narrative,
        narrative_check=check,
        timings=timings,
        total_ms=round(total_ms, 1),
        model_version=str(_bundle().get("version", "unknown")),
        transactions=[t.model_dump() for t in case.transactions],
        input_summary={
            "n_tx": len(case.transactions),
            "n_counterparty_clusters": len(set(clusters.values())),
            "merged_identity_groups": merged_groups[:6],
            "ml_probability": round(cal_p, 4),
            "rule_component": round(rc, 4),
            "rule_weight": RULE_WEIGHT,
            "ml_weight": ML_WEIGHT,
            "generated_at": datetime.now(UTC).isoformat(),
            "llm": llm_stats.__dict__ if llm_stats else None,
        },
    )
    return result, events
