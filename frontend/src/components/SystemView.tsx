import { useEffect, useState } from "react";
import { getMetrics, getSystem } from "../api";

function Metric({ v, l, s }: { v: string; l: string; s?: string }) {
  return (
    <div className="metric">
      <div className="v">{v}</div>
      <div className="l">{l}</div>
      {s && <div className="s">{s}</div>}
    </div>
  );
}

export default function SystemView() {
  const [metrics, setMetrics] = useState<any>({});
  const [facts, setFacts] = useState<any>({});

  useEffect(() => {
    getMetrics().then(setMetrics);
    getSystem().then(setFacts);
  }, []);

  const ev = metrics.eval_report ?? {};
  const tr = metrics.train_report ?? {};
  const test = ev.test ?? {};
  const novel = ev.novel_variants ?? {};
  const gen = ev.generalization ?? {};
  const lat = ev.latency ?? {};
  const nar = ev.narrative ?? {};
  const fail = ev.failures ?? {};
  const sources: any[] = facts.data_sources ?? [];
  const cost = facts.cost_model ?? {};

  return (
    <>
      <div className="title-line">
        <h2>System & evidence</h2>
        <span className="muted small">
          architecture, measured quality, data provenance, deployment and cost — everything the
          jury can audit
        </span>
      </div>

      <div className="card">
        <h3>
          Measured quality
          <span className="hint">held-out synthetic test set · eval/run_eval.py · reproducible</span>
        </h3>
        <div className="metrics">
          <Metric
            v={test.model_roc_auc ?? "—"}
            l="ROC-AUC (test)"
            s={`${test.n ?? "?"} cases, ${test.n_suspicious ?? "?"} suspicious`}
          />
          <Metric
            v={test.ensemble_at_band50_precision_at_prevalence?.precision ?? "—"}
            l="precision @10% prevalence"
            s="ensemble, band ≥50"
          />
          <Metric
            v={test.ensemble_at_band50_precision_at_prevalence?.recall ?? "—"}
            l="recall (test)"
            s={`FPR ${test.ensemble_at_band50_precision_at_prevalence?.fpr ?? "—"}`}
          />
          <Metric
            v={test.at_band_50?.rules?.fpr ?? "—"}
            l="rule-only FPR (test)"
            s="the pain the model removes"
          />
          <Metric
            v={test.at_band_50?.rules?.recall ?? "—"}
            l="rule-only recall (test)"
            s="deterministic layer alone"
          />
          <Metric
            v={novel.model_roc_auc ?? "—"}
            l="ROC-AUC (novel variants)"
            s="held-out typology variants"
          />
          <Metric
            v={lat.pipeline_no_llm_ms?.p50 ?? "—"}
            l="pipeline p50 (ms)"
            s={`p95 ${lat.pipeline_no_llm_ms?.p95 ?? "—"} ms, no LLM`}
          />
          <Metric
            v={lat.pipeline_no_llm_ms ? `${(lat.pipeline_no_llm_ms.p95 / 1000).toFixed(2)} s` : "—"}
            l="p95 end-to-end, no LLM"
            s="deterministic stages"
          />
          <Metric
            v={nar.mean_citation_precision ?? "—"}
            l="narrative citation precision"
            s={`${nar.sample_n ?? 0} notes, ${nar.mode ?? ""}`}
          />
          <Metric
            v={nar.llm_latency_ms ? `${(nar.llm_latency_ms.p50 / 1000).toFixed(1)} s` : "—"}
            l="LLM narrative p50"
            s={nar.avg_tokens?.prompt ? `~${nar.avg_tokens.prompt + nar.avg_tokens.completion} tokens` : ""}
          />
          <Metric v={tr.val_ece ?? "—"} l="calibration ECE (val)" s="isotonic-calibrated" />
          <Metric v={fail.fp_count ?? "—"} l="known FPs @ band 50" s="see failure list below" />
        </div>

        {Object.keys(gen).length > 0 && (
          <div className="note" style={{ marginTop: 12 }}>
            <b>Generalization:</b> model AUC {gen.model_auc_test} → {gen.model_auc_novel} on novel
            variants; ensemble recall {gen.ensemble_recall_test} → {gen.ensemble_recall_novel};
            rule-layer recall {gen.rules_recall_test} → {gen.rules_recall_novel}. The rule layer is
            what degrades — the model layer is why the product still works when criminals change
            their pattern.
          </div>
        )}

        {(fail.false_positives_at_50?.length > 0 || fail.false_negatives_at_50?.length > 0) && (
          <div className="grid-3" style={{ marginTop: 12 }}>
            <div className="card">
              <h3>False positives (honest list)</h3>
              <div className="evi-list">
                {(fail.false_positives_at_50 ?? []).map((f: any) => (
                  <div className="evi" key={f.case_id}>
                    <span className="id">{f.case_id}</span>
                    <span>
                      score {f.score} · {f.label} · rules {f.rules.join(", ") || "—"}
                    </span>
                  </div>
                ))}
                {!fail.false_positives_at_50?.length && <span className="muted small">none at band 50</span>}
              </div>
            </div>
            <div className="card">
              <h3>False negatives (honest list)</h3>
              <div className="evi-list">
                {(fail.false_negatives_at_50 ?? []).map((f: any) => (
                  <div className="evi" key={f.case_id}>
                    <span className="id">{f.case_id}</span>
                    <span>
                      score {f.score} · {f.label} · rules {f.rules.join(", ") || "—"}
                    </span>
                  </div>
                ))}
                {!fail.false_negatives_at_50?.length && <span className="muted small">none at band 50</span>}
              </div>
            </div>
            <div className="card">
              <h3>Per-typology coverage (test)</h3>
              <table className="data">
                <thead>
                  <tr>
                    <th>typology</th>
                    <th>n</th>
                    <th>rules</th>
                    <th>ensemble</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(test.per_typology ?? {}).map(([k, v]: any) => (
                    <tr key={k}>
                      <td>{k}</td>
                      <td>{v.n}</td>
                      <td>{(v.rule_recall ?? v.rule_flag_rate ?? 0).toFixed(2)}</td>
                      <td>
                        {(v["ensemble_recall@50"] ?? v["ensemble_flag_rate@50"] ?? 0).toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div className="grid2">
        <div className="card">
          <h3>
            Architecture
            <span className="hint">what runs where</span>
          </h3>
          <div className="arch">
            <div className="box">
              <b>1 · Intake</b> — CSV/JSON/queue → normaliser (UZS amounts, dd.mm.yyyy, Latin/Cyrillic
              names) → chronological case
            </div>
            <div className="box">
              <b>2 · Entity resolution</b> — union-find over account / normalised name / phone;
              transliteration-aware (Temur = Тemür = Тимур)
            </div>
            <div className="box">
              <b>3 · Features</b> — 49 analyst-readable features (threshold proximity, drain speed,
              fan-in, triangles, memos, turnover mismatch…)
            </div>
            <div className="box">
              <b>4 · Scenario rules</b> — SC-01…SC-06 typology library, evidence-linked, mapped to
              FATF families (explainability + coverage)
            </div>
            <div className="box">
              <b>5 · GBM risk model</b> — HistGradientBoosting on synthetic casebook, isotonic
              calibration, leave-one-out feature attribution
            </div>
            <div className="box">
              <b>6 · Ensemble score</b> = 0.7·P(model) + 0.3·rule severity → band 0–100
            </div>
            <div className="box">
              <b>7 · Narrative (local LLM)</b> — Qwen2.5-3B Q4 via llama.cpp, OpenAI-compatible
              endpoint, evidence-only prompt
            </div>
            <div className="box">
              <b>8 · Citation verifier</b> — deterministic: every [E#] must exist, every money-scale
              number must be in evidence; violations flagged
            </div>
            <div className="box">
              <b>9 · Decision + audit log</b> — human decision, score, check result → append-only
              JSONL
            </div>
            <div style={{ marginTop: 8 }} className="note">
              <b>Data never leaves the perimeter:</b> the prototype ships llama.cpp + GGUF inside the
              container; the same image runs on-prem. External API is not required at any step —
              swapping in vLLM behind the same OpenAI-compatible URL is the production path.
            </div>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="card">
            <h3>
              Data sources & licences
              <span className="hint">required by the challenge rules</span>
            </h3>
            <table className="data">
              <thead>
                <tr>
                  <th>source</th>
                  <th>what</th>
                  <th>licence</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => (
                  <tr key={s.name}>
                    <td>{s.name}</td>
                    <td className="muted">{s.what}</td>
                    <td>{s.licence}</td>
                  </tr>
                ))}
                {!sources.length && (
                  <tr>
                    <td colSpan={3} className="muted">
                      see repo README / eval/results/system_facts.json
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="card">
            <h3>Cost model</h3>
            {Object.keys(cost).length ? (
              <div className="kv">
                {Object.entries(cost).map(([k, v]) => (
                  <div key={k} style={{ display: "contents" }}>
                    <dt>{k.split("_").join(" ")}</dt>
                    <dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
                  </div>
                ))}
              </div>
            ) : (
              <div className="muted small">see README / system facts</div>
            )}
          </div>

          <div className="card">
            <h3>Human-in-the-loop & audit</h3>
            <div className="small muted" style={{ lineHeight: 1.8 }}>
              <div>· Model proposes score + draft note; <b>only a named analyst</b> records dismiss / escalate / STR.</div>
              <div>· Narrative cannot go out unverified — citations and numbers are machine-checked.</div>
              <div>· Every decision appends: case, score, rule hits, check result, model version.</div>
              <div>· Failure cases are published above, not hidden.</div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
