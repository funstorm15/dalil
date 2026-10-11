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
                   top_features: list[dict], score: float, cal_p: float, rc: float,
                   imputed: dict[str, float]) -> list[EvidenceItem]:
    ev: list[EvidenceItem] = []
    n = 0

    def add(kind: str, text: str, ref: str = "") -> str:
        nonlocal n
        n += 1
        eid = f"E{n}"
        ev.append(EvidenceItem(id=eid, kind=kind, text=text, ref=ref))
        return eid

    age = (f"account age {case.account_age_days} d" if case.account_age_days is not None
           else "account age NOT PROVIDED")
    turnover = (f"declared turnover {case.declared_turnover_monthly / 1e6:.1f} mln UZS/month"
                if case.declared_turnover_monthly is not None else "declared turnover NOT PROVIDED")
    add("subject", f"Subject: {case.subject_name} ({case.subject_kind}, {age}, {turnover}, "
                   f"branch {case.branch or 'n/a'})", case.subject_account)
    matched = [h for h in hits if h.matched]
    imp = (f"; model inputs imputed with training medians for: {', '.join(sorted(imputed))}"
           if imputed else "")
    add("model", f"Model output: DALIL score {score:.1f}/100 ({band(score)}), calibrated ML "
                 f"probability {cal_p:.2f}, rule component {rc:.2f}, typology rules matched "
                 f"{len(matched)} of {len(hits)}{imp}", "score")
    txs = case.transactions
    ins = [t for t in txs if t.direction == "in"]
    outs = [t for t in txs if t.direction == "out"]
    cps = {(t.from_name if t.direction == "in" else t.to_name) for t in txs}
    period = f"{txs[0].ts[:10]} to {txs[-1].ts[:10]}" if txs else "n/a"
    add("aggregate", f"Case window: {len(txs)} transactions ({len(ins)} in, {len(outs)} out) "
                     f"from {period}; inflow total {sum(t.amount for t in ins) / 1e6:.1f} mln UZS; "
                     f"outflow total {sum(t.amount for t in outs) / 1e6:.1f} mln UZS; "
                     f"{len(cps)} distinct counterparty names", "window")
    for tf in top_features[:4]:
        add("feature", f"{tf['feature']} = {fmt_feature(tf['feature'], tf['value'])} "
                       f"(score impact {tf['impact']:+.1f} pp)", tf["feature"])
    for h in matched:
        add("scenario", f"{h.code} {h.name}: {h.detail}", h.code)

    # notable transactions: scenario-referenced first, then the largest
    tx_by_id = {t.id: t for t in txs}
    cited: set[str] = set()
    for h in hits:
        for tid in h.evidence:
            if tid in tx_by_id and tid not in cited:
                cited.add(tid)
                add("transaction", _tx_text(tx_by_id[tid]), tid)
                if len(cited) >= 5:
                    break
        if len(cited) >= 5:
            break
    if len(cited) < 3:
        for t in sorted(txs, key=lambda x: -x.amount)[:4]:
            if t.id not in cited:
                add("transaction", _tx_text(t), t.id)
                cited.add(t.id)
    return ev


def counterparty(t: Transaction) -> tuple[str, str]:
    """(name, kind) of the party on the OTHER side from the subject."""
    if t.direction == "in":
        return t.from_name, t.from_kind
    return t.to_name, t.to_kind


def _tx_text(t: Transaction) -> str:
    cp_name, _ = counterparty(t)
    side = "from" if t.direction == "in" else "to"
    memo = f", memo='{t.memo}'" if t.memo else ""
    return (f"tx {t.id} {t.ts} {t.direction} {t.amount / 1e6:.1f} mln UZS "
            f"{side} {cp_name} via {t.channel}{memo}")


def deterministic_narrative(case, hits: list[ScenarioHit], evidence: list[EvidenceItem],
                            score: float) -> str:
    """Template note assembled only from evidence text — the primary note."""
    by_kind: dict[str, list[EvidenceItem]] = {}
    for e in evidence:
        by_kind.setdefault(e.kind, []).append(e)
    model_ev = by_kind["model"][0]
    agg_ev = by_kind["aggregate"][0]
    lines = ["**1) SUMMARY** (template — assembled from evidence, no LLM)",
             f"{model_ev.text} [{model_ev.id}].",
             f"{agg_ev.text} [{agg_ev.id}].", ""]
    lines.append("**2) TYPOLOGY**")
    if by_kind.get("scenario"):
        for e in by_kind["scenario"]:
            lines.append(f"- {e.text} [{e.id}]")
    else:
        lines.append(f"- No typology rule matched; the score is driven by behavioural features [{model_ev.id}].")
    lines += ["", "**3) KEY EVIDENCE**"]
    for e in by_kind.get("feature", [])[:3] + by_kind.get("transaction", [])[:3]:
        lines.append(f"- {e.text} [{e.id}]")
    subj = by_kind["subject"][0]
    lines += ["", "**4) NEXT STEPS**",
              f"- {'Review for escalation to L2' if score >= 50 else 'Review and document the rationale'}; "
              f"verify counterparty identities against KYC [{subj.id}].",
              "- Compare with prior account history (outside this prototype).",
              "- The analyst decides; this note does not establish that laundering occurred."]
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
    imputed: dict[str, float] = {}
    with stage("features"):
        medians = _bundle().get("medians") or {}
        if case.account_age_days is None:
            imputed["account_age_days"] = float(medians.get("account_age_days", 0.0))
        if case.declared_turnover_monthly is None:
            imputed["declared_turnover_monthly"] = float(medians.get("declared_turnover_monthly", 0.0))
        features = extract_features(case, fill=imputed)
    with stage("scenarios"):
        hits = run_scenarios(case)
    with stage("model"):
        raw_p, cal_p = predict_ml(features)
        top = feature_contributions(features)
    with stage("score"):
        rc = rule_component(hits)
        score = 100.0 * (ML_WEIGHT * cal_p + RULE_WEIGHT * rc)

    evidence = build_evidence(case, features, hits, top, score, cal_p, rc, imputed)
    narrative = deterministic_narrative(case, hits, evidence, score)

    llm_draft: dict | None = None
    llm_stats = None
    with stage("narrative", "experimental local-LLM draft" if want_narrative else "skipped"):
        if want_narrative:
            case_brief = (
                f"case_id={case.case_id}; subject={case.subject_name} ({case.subject_kind}). "
                "All numbers are in the evidence list; cite them."
            )
            ev_lines = [f"[{e.id}] ({e.kind}) {e.text}" for e in evidence]
            client = llm or LLMClient()
            t0 = time.perf_counter()
            try:
                text = client.chat(SYSTEM_PROMPT, build_user_prompt(case_brief, ev_lines))
                llm_stats = client.last_stats
                complete = llm_stats.finish_reason != "length"
                check_d = verify_narrative(text, evidence, complete=complete)
                llm_draft = {
                    "status": "complete" if complete else "truncated",
                    "text": text,
                    "check": check_d.model_dump(),
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "model": client.model,
                    "finish_reason": llm_stats.finish_reason,
                }
                if not complete:
                    events[-1]["detail"] = "LLM draft hit the token limit — marked INCOMPLETE"
            except LLMUnavailable as e:
                llm_stats = client.last_stats
                llm_draft = {"status": "unavailable", "text": "", "check": None,
                             "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                             "model": client.model, "error": str(e)[:200]}
                events[-1]["detail"] = f"LLM unavailable ({e}); template note only"

    with stage("verify"):
        check = verify_narrative(narrative, evidence)
        check.mode = "deterministic"

    total_ms = (time.perf_counter() - t_start) * 1000
    top_features = [
        {"feature": t["feature"], "value": t["value"], "display": fmt_feature(t["feature"], t["value"]),
         "impact": t["impact"], "baseline": t["baseline"]}
        for t in top
    ]
    hint = decision_hint(score)
    if imputed:
        hint = (f"PROVISIONAL — {', '.join(sorted(imputed))} not provided (model inputs imputed); "
                f"score-based hint: {hint}")
    result = AnalysisResult(
        case_id=case.case_id,
        score=round(score, 1),
        risk_band=band(score),  # type: ignore[arg-type]
        decision_hint=hint,
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
        llm_draft=llm_draft,
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
            "imputed": imputed,
            "amount_format": case.amount_format,
            "warnings": _input_warnings(case, imputed),
        },
    )
    return result, events


def _input_warnings(case, imputed: dict[str, float] | None = None) -> list[str]:
    """Honest caveats surfaced in the UI — never silently swallowed."""
    w: list[str] = list(case.input_notes)
    n = len(case.transactions)
    if n < 5:
        w.append(f"only {n} transactions — behavioural features are unreliable on thin history")
    if case.declared_turnover_monthly is None:
        w.append("declared turnover not provided — SC-06 not evaluated; model input imputed with the "
                 f"training median ({(imputed or {}).get('declared_turnover_monthly', 0) / 1e6:.1f} mln UZS/month)")
    if case.account_age_days is None:
        w.append("account age not provided — SC-03 not evaluated; model input imputed with the "
                 f"training median ({(imputed or {}).get('account_age_days', 0):.0f} d)")
    if imputed:
        w.append("score uses imputed subject metadata — treat the recommendation as provisional")
    if case.subject_name.strip().lower() in ("", "subject account", "subj"):
        w.append("subject name not provided — shown as 'Subject account'")
    return w
