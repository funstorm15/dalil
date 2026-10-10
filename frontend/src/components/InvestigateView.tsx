import { useEffect, useMemo, useRef, useState } from "react";
import { SAMPLE_CSV, analyze, getCases, sendDecision } from "../api";
import type { AnalysisResult, CaseOption, StageEvent } from "../types";

const STAGE_LABEL: Record<string, string> = {
  ingest: "ingest · parse",
  entities: "entity resolution",
  features: "features",
  scenarios: "typology rules",
  model: "GBM risk model",
  score: "ensemble score",
  narrative: "LLM narrative",
  verify: "citation verify",
};

function bandColor(band?: string): string {
  switch (band) {
    case "critical":
      return "var(--critical)";
    case "high":
      return "var(--high)";
    case "medium":
      return "var(--medium)";
    case "low":
      return "var(--low)";
    default:
      return "var(--accent)";
  }
}

function Gauge({ score, band }: { score: number; band?: string }) {
  const r = 54;
  const c = Math.PI * r * 1.5;
  const len = Math.max(0, Math.min(score, 100)) / 100 * c;
  return (
    <div className="gauge-wrap">
      <svg width="150" height="120" viewBox="0 0 150 120">
        <path
          d="M 21 99 A 54 54 0 1 1 129 99"
          fill="none"
          stroke="var(--panel2)"
          strokeWidth="12"
          strokeLinecap="round"
        />
        <path
          d="M 21 99 A 54 54 0 1 1 129 99"
          fill="none"
          stroke={bandColor(band)}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={`${len} ${c}`}
          style={{ transition: "stroke-dasharray 0.7s ease-out" }}
        />
        <text x="75" y="86" textAnchor="middle" fill="var(--text)" fontSize="34" fontWeight="700"
          fontFamily="var(--mono)">
          {Math.round(score)}
        </text>
      </svg>
      <div>
        <div className="gauge-lab">DALIL score</div>
        {band && <span className={`badge ${band}`}>{band.toUpperCase()}</span>}
      </div>
    </div>
  );
}

function renderNarrative(text: string, badIds: Set<string>, onCite: (id: string) => void) {
  const parts = text.split(/(\[E\d{1,3}\])/g);
  return parts.map((p, i) => {
    const m = p.match(/^\[(E\d{1,3})\]$/);
    if (m) {
      const id = m[1];
      return (
        <span
          key={i}
          className={`cite ${badIds.has(id) ? "bad" : ""}`}
          onClick={() => onCite(id)}
          title={badIds.has(id) ? "citation not found in evidence" : "show evidence"}
        >
          {id}
        </span>
      );
    }
    return <span key={i}>{p}</span>;
  });
}

export default function InvestigateView({
  caseId,
  onCaseChange,
  onDecided,
}: {
  caseId: string | null;
  onCaseChange: (id: string | null) => void;
  onDecided: () => void;
}) {
  const [cases, setCases] = useState<CaseOption[]>([]);
  const [csv, setCsv] = useState("");
  const [mode, setMode] = useState<"case" | "csv">(caseId ? "case" : "csv");
  const [stages, setStages] = useState<StageEvent[]>([]);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [wall, setWall] = useState<number | null>(null);
  const [hl, setHl] = useState<string>("");
  const [note, setNote] = useState("");
  const [decision, setDecision] = useState("");
  const [toast, setToast] = useState("");
  const stagesRef = useRef<StageEvent[]>([]);

  useEffect(() => {
    getCases().then((c) => {
      setCases(c);
      if (!caseId && c.length) onCaseChange(c[0].case_id);
    });
  }, [caseId, onCaseChange]);

  useEffect(() => {
    if (caseId) setMode("case");
  }, [caseId]);

  const run = async () => {
    setRunning(true);
    setError("");
    setResult(null);
    setWall(null);
    setStages([]);
    stagesRef.current = [];
    const payload = mode === "case" ? { case_id: caseId! } : { csv_text: csv || SAMPLE_CSV };
    await analyze(payload, {
      onStage: (ev) => {
        const arr = [...stagesRef.current];
        const i = arr.findIndex((s) => s.stage === ev.stage);
        if (i >= 0) arr[i] = ev;
        else arr.push(ev);
        stagesRef.current = arr;
        setStages([...arr]);
      },
      onResult: (res) => setResult(res),
      onError: (msg) => setError(msg),
      onDone: (ms) => setWall(ms),
    });
    setRunning(false);
  };

  const decide = async (d: string) => {
    if (!result) return;
    setDecision(d);
    const ok = await sendDecision({
      decision: { case_id: result.case_id, decision: d, analyst: "demo-analyst", note },
      result,
    });
    setToast(ok ? `Recorded: ${d} · ${result.case_id}` : "Failed to record decision");
    setTimeout(() => setToast(""), 3200);
    onDecided();
  };

  const badCites = useMemo(() => new Set(result?.narrative_check.invalid_citations ?? []), [result]);

  const evidById = useMemo(() => {
    const m = new Map<string, string>();
    result?.evidence.forEach((e) => m.set(e.id, e.text));
    return m;
  }, [result]);

  const selectedCase = cases.find((c) => c.case_id === caseId);

  return (
    <>
      <div className="title-line">
        <h2>Investigate</h2>
        <span className="muted small">
          pick an alert case, or paste your own transactions (jury input) — the pipeline runs live
        </span>
        <div className="sep" />
        {result && (
          <span className="muted small mono">
            {result.model_version} · {result.total_ms} ms total
            {wall ? ` · stream ${wall} ms` : ""}
          </span>
        )}
      </div>

      <div className="grid2">
        {/* ---------- input + stage trace ---------- */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="card">
            <h3>Input</h3>
            <div className="chips" style={{ marginBottom: 10 }}>
              <button className={`btn sm ${mode === "case" ? "" : "ghost"}`} onClick={() => setMode("case")}>
                Demo case
              </button>
              <button className={`btn sm ${mode === "csv" ? "" : "ghost"}`} onClick={() => setMode("csv")}>
                Your CSV / jury input
              </button>
            </div>
            {mode === "case" ? (
              <select value={caseId ?? ""} onChange={(e) => onCaseChange(e.target.value)}>
                {cases.map((c) => (
                  <option key={c.case_id} value={c.case_id}>
                    {c.case_id} · {c.subject_name} · {c.n_tx} txns
                  </option>
                ))}
              </select>
            ) : (
              <>
                <textarea
                  rows={11}
                  placeholder="ts, amount, direction, counterparty_name, counterparty_kind, channel, memo …"
                  value={csv}
                  onChange={(e) => setCsv(e.target.value)}
                />
                <div className="center" style={{ marginTop: 8 }}>
                  <button className="btn ghost sm" onClick={() => setCsv(SAMPLE_CSV)}>
                    load template
                  </button>
                  <button
                    className="btn ghost sm"
                    onClick={() => {
                      const el = document.createElement("input");
                      el.type = "file";
                      el.accept = ".csv,.txt";
                      el.onchange = async () => {
                        const f = el.files?.[0];
                        if (f) setCsv(await f.text());
                      };
                      el.click();
                    }}
                  >
                    upload .csv
                  </button>
                </div>
                <div className="small muted" style={{ marginTop: 6 }}>
                  RU/EN headers, messy amounts (“43 500 000”, “4,5 млн”) and dd.mm.yyyy dates are
                  normalised automatically.
                </div>
              </>
            )}
            <div style={{ marginTop: 12 }}>
              <button className="btn" disabled={running || (mode === "case" && !caseId)} onClick={run}>
                {running ? "Analysing…" : "Run investigation"}
              </button>
            </div>
            {error && <div className="note err" style={{ marginTop: 10 }}>{error}</div>}
          </div>

          <div className="card">
            <h3>
              Pipeline trace
              <span className="hint">live stage timings</span>
            </h3>
            <div className="stages">
              {stages.map((s) => (
                <div key={s.stage} className={`stage ${s.status}`}>
                  {s.status === "running" ? (
                    <span className="spin" />
                  ) : (
                    <span style={{ color: "var(--low)" }}>✓</span>
                  )}
                  <span className="nm">{STAGE_LABEL[s.stage] ?? s.stage}</span>
                  <span className="st">
                    {s.status === "running" ? "…" : `${s.ms?.toFixed(1)} ms`}
                  </span>
                </div>
              ))}
              {!stages.length && <div className="muted small">no run yet</div>}
            </div>
            {result && (
              <div className="note" style={{ marginTop: 10 }}>
                {result.input_summary.n_tx} transactions ·{" "}
                {result.input_summary.n_counterparty_clusters} resolved counterparties
                {result.input_summary.merged_identity_groups?.length
                  ? ` · ${result.input_summary.merged_identity_groups.length} merged identity groups (transliteration/phone)`
                  : ""}
              </div>
            )}
          </div>
        </div>

        {/* ---------- results ---------- */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {!result && !running && (
            <div className="card">
              <div className="muted">
                Run an investigation to see: live stage trace, risk score with feature attribution,
                typology rule hits with evidence, an evidence-grounded narrative (local LLM) with
                automatic citation verification, and the analyst decision/audit flow.
              </div>
            </div>
          )}
          {running && !result && (
            <div className="card">
              <div className="center">
                <span className="spin" /> <span>running pipeline…</span>
              </div>
            </div>
          )}
          {result && (
            <>
              <div className="card">
                <div className="gauge-wrap" style={{ justifyContent: "space-between" }}>
                  <Gauge score={result.score} band={result.risk_band} />
                  <div className="kv" style={{ flex: 1 }}>
                    <dt>case</dt>
                    <dd>{result.case_id}</dd>
                    <dt>ML probability</dt>
                    <dd>{(result.input_summary.ml_probability ?? 0).toFixed(3)}</dd>
                    <dt>rule component</dt>
                    <dd>
                      {(result.input_summary.rule_component ?? 0).toFixed(3)} (weight{" "}
                      {result.input_summary.ml_weight}/{result.input_summary.rule_weight})
                    </dd>
                    <dt>recommendation</dt>
                    <dd style={{ color: bandColor(result.risk_band) }}>{result.decision_hint}</dd>
                  </div>
                </div>
              </div>

              <div className="card">
                <h3>
                  Typology rules
                  <span className="hint">deterministic layer · evidence-linked</span>
                </h3>
                <div className="scen">
                  {result.scenarios.map((s) => (
                    <div key={s.code} className={`scen-row ${s.matched ? "hit" : ""}`}>
                      <div className="scen-head">
                        <span className="code">{s.code}</span>
                        <span>{s.name}</span>
                        <span className="sep" />
                        <span className={`badge ${s.matched ? "high" : "neutral"}`}>
                          {s.matched ? `hit · sev ${s.severity.toFixed(2)}` : "no match"}
                        </span>
                      </div>
                      <div className="scen-detail">
                        {s.detail}
                        {s.name_uz && <span className="muted"> · uz: {s.name_uz}</span>}
                      </div>
                      {s.matched && s.evidence.length > 0 && (
                        <div className="txrefs">
                          {s.evidence.map((t) => (
                            <span key={t} className="txref" onClick={() => setHl(t)}>
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div className="card">
                <h3>
                  Investigation note
                  <span className="hint">
                    {result.narrative_check.mode === "llm"
                      ? "local LLM · verified against evidence"
                      : "deterministic extract · LLM offline"}
                  </span>
                </h3>
                <div className="narrative">
                  {renderNarrative(result.narrative, badCites, (id) => setHl(id))}
                </div>
                <div className="chips" style={{ marginTop: 10 }}>
                  <span className={`badge ${result.narrative_check.citation_precision >= 1 ? "low" : "high"}`}>
                    citation precision {result.narrative_check.citation_precision.toFixed(2)}
                  </span>
                  <span className="badge neutral">
                    {result.narrative_check.checked_citations} citations checked
                  </span>
                  {result.narrative_check.invalid_citations.length > 0 && (
                    <span className="badge critical">
                      invalid: {result.narrative_check.invalid_citations.join(", ")}
                    </span>
                  )}
                  {result.narrative_check.unverified_numbers.length > 0 && (
                    <span className="badge high">
                      unsourced numbers: {result.narrative_check.unverified_numbers.join(", ")}
                    </span>
                  )}
                </div>
              </div>

              <div className="grid-3">
                <div className="card">
                  <h3>
                    Evidence
                    <span className="hint">click to highlight</span>
                  </h3>
                  <div className="evi-list">
                    {result.evidence.map((e) => (
                      <div
                        key={e.id}
                        className={`evi ${hl.startsWith(e.id) || (hl && e.ref === hl) ? "hl" : ""}`}
                        onClick={() => setHl(e.ref || e.id)}
                      >
                        <span className="id">{e.id}</span>
                        <div>
                          <div className="kind">{e.kind}</div>
                          <div>{e.text}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="card">
                  <h3>
                    Score attribution
                    <span className="hint">leave-one-out vs typical</span>
                  </h3>
                  <div className="feat">
                    {result.top_features.map((f) => {
                      const w = Math.min(50, Math.abs(f.impact) * 6);
                      const pos = f.impact >= 0;
                      return (
                        <div className="feat-row" key={f.feature}>
                          <span className="nm" title={f.feature}>
                            {f.feature}
                          </span>
                          <span className="feat-bar">
                            <i
                              style={{
                                left: pos ? "50%" : `${50 - w}%`,
                                width: `${w}%`,
                                background: pos ? "var(--critical)" : "var(--low)",
                              }}
                            />
                          </span>
                          <span className="val">
                            {f.impact > 0 ? "+" : ""}
                            {f.impact.toFixed(1)}pp
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  <div className="small muted" style={{ marginTop: 8 }}>
                    {result.top_features[0]
                      ? `“${result.top_features[0].feature}” moved the score most in this case.`
                      : ""}
                  </div>
                </div>

                <div className="card">
                  <h3>Analyst decision</h3>
                  <div className="decisions">
                    <button className="btn good sm" disabled={!result} onClick={() => decide("dismiss")}>
                      Dismiss
                    </button>
                    <button className="btn warn sm" disabled={!result} onClick={() => decide("escalate")}>
                      Escalate L2
                    </button>
                    <button className="btn danger sm" disabled={!result} onClick={() => decide("file_str")}>
                      File STR
                    </button>
                    <button className="btn ghost sm" disabled={!result} onClick={() => decide("request_info")}>
                      Request info
                    </button>
                  </div>
                  <textarea
                    rows={3}
                    style={{ marginTop: 10 }}
                    placeholder="analyst note (goes into the audit log)"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                  <div className="small muted" style={{ marginTop: 8 }}>
                    Decision + score + narrative check are appended to the audit log.
                  </div>
                </div>
              </div>

              <div className="card">
                <h3>
                  Transactions
                  <span className="hint">
                    {selectedCase ? selectedCase.subject_name : "jury input"} · click evidence refs to
                    highlight
                  </span>
                </h3>
                <div className="scrollY">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>id</th>
                        <th>ts</th>
                        <th>dir</th>
                        <th>amount UZS</th>
                        <th>counterparty</th>
                        <th>channel</th>
                        <th>memo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.transactions.map((t) => {
                        const cp = t.direction === "in" ? t.from_name : t.to_name;
                        return (
                          <tr key={t.id} className={hl === t.id ? "hl" : ""} id={`tx-${t.id}`}>
                            <td>{t.id}</td>
                            <td>{t.ts}</td>
                            <td style={{ color: t.direction === "in" ? "var(--low)" : "var(--high)" }}>
                              {t.direction}
                            </td>
                            <td>
                              {t.amount.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                            </td>
                            <td>
                              {cp} <span className="muted">({t.direction === "in" ? t.from_kind : t.to_kind})</span>
                            </td>
                            <td>{t.channel}</td>
                            <td className="muted">{t.memo || "—"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {evidById.size > 0 && hl && evidById.has(hl) && (
        <div className="toast" style={{ maxWidth: 420 }}>
          <b>{hl}</b> — {evidById.get(hl)}
        </div>
      )}
      {toast && <div className="toast">{toast}</div>}
    </>
  );
}
