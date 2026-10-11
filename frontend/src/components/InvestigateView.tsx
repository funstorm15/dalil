import { useEffect, useMemo, useRef, useState } from "react";
import {
  SAMPLE_CSV,
  analyze,
  exportBundle,
  getAnalysis,
  getCases,
  sendDecision,
  verifyBundle,
} from "../api";
import type {
  AnalysisResult,
  AuditEntry,
  CaseOption,
  NarrativeCheck,
  StageEvent,
  VerifyResult,
} from "../types";

// only ids + form text live in the browser; results are re-fetched from the server
const SESSION_KEY = "dalil:session:v2";

const STAGE_LABEL: Record<string, string> = {
  ingest: "ingest · parse",
  entities: "entity resolution",
  features: "features",
  scenarios: "typology rules",
  model: "GBM risk model",
  score: "ensemble score",
  narrative: "LLM draft (experimental)",
  verify: "note checks",
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

function CheckBadges({ check }: { check: NarrativeCheck }) {
  const idsOk = check.checked_citations > 0 && check.invalid_citations.length === 0;
  const numIssues =
    check.unsupported_numbers.length + check.miscited_numbers.length + check.uncited_numbers.length;
  return (
    <>
      <div className="chips" style={{ marginTop: 10 }}>
        <span className={`badge ${idsOk ? "low" : "high"}`} title="every [E#] must exist in the evidence list">
          citation IDs exist: {check.checked_citations - check.invalid_citations.length}/
          {check.checked_citations}
        </span>
        <span
          className={`badge ${numIssues === 0 ? "low" : "high"}`}
          title="numbers, amounts (incl. mln) and ISO dates must match the evidence cited in the same sentence"
        >
          numbers & dates match cited evidence: {check.numbers_supported}/{check.numbers_checked}
        </span>
        <span className={`badge ${check.complete ? "neutral" : "critical"}`}>
          {check.complete ? "text complete" : "INCOMPLETE — hit token limit"}
        </span>
        <span
          className="badge neutral"
          title="a valid citation and matching numbers do not make a claim true — the analyst reviews the meaning"
        >
          meaning: NOT machine-verified
        </span>
      </div>
      {(check.invalid_citations.length > 0 || numIssues > 0) && (
        <div className="note warn small" style={{ marginTop: 8 }}>
          {check.invalid_citations.length > 0 && (
            <div>⚠ citation IDs not in evidence: {check.invalid_citations.join(", ")}</div>
          )}
          {check.unsupported_numbers.length > 0 && (
            <div>⚠ in no evidence item: {check.unsupported_numbers.join(", ")}</div>
          )}
          {check.miscited_numbers.length > 0 && (
            <div>⚠ present only in evidence that is NOT cited there: {check.miscited_numbers.join(", ")}</div>
          )}
          {check.uncited_numbers.length > 0 && (
            <div>⚠ stated without a citation: {check.uncited_numbers.join(", ")}</div>
          )}
          <div className="muted">Warnings only — they do not block a decision or an export.</div>
        </div>
      )}
    </>
  );
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
  const [amountFormat, setAmountFormat] = useState("strict");
  const [wantLlm, setWantLlm] = useState(true);
  const [stages, setStages] = useState<StageEvent[]>([]);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [wall, setWall] = useState<number | null>(null);
  const [hlEv, setHlEv] = useState("");
  const [hlTx, setHlTx] = useState("");
  const [analyst, setAnalyst] = useState("");
  const [note, setNote] = useState("");
  const [decisions, setDecisions] = useState<AuditEntry[]>([]);
  const [toast, setToast] = useState("");
  const [restored, setRestored] = useState("");
  const [exporting, setExporting] = useState(false);
  const [verify, setVerify] = useState<VerifyResult | null>(null);
  const stagesRef = useRef<StageEvent[]>([]);
  const restoredMode = useRef<string | null>(null);

  useEffect(() => {
    getCases().then((c) => {
      setCases(c);
      if (!caseId && c.length) onCaseChange(c[0].case_id);
    });
  }, [caseId, onCaseChange]);

  useEffect(() => {
    if (caseId) setMode("case");
  }, [caseId]);

  // after a reload: re-fetch the analysis and its decisions FROM THE SERVER by analysis_id
  useEffect(() => {
    let d: any = null;
    try {
      d = JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null");
    } catch {
      d = null;
    }
    if (!d) return;
    restoredMode.current = d.mode ?? null;
    if (d.csv) setCsv(d.csv);
    if (d.analyst) setAnalyst(d.analyst);
    if (d.note) setNote(d.note);
    if (d.amountFormat) setAmountFormat(d.amountFormat);
    if (d.caseId) onCaseChange(d.caseId);
    if (!d.analysisId) return;
    getAnalysis(d.analysisId).then((rec) => {
      if (!rec) {
        setRestored("saved analysis not found on this server — run it again");
        return;
      }
      setResult(rec.result);
      setDecisions(rec.decisions);
      setRestored("restored from server after reload");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (restored && restoredMode.current) {
      setMode(restoredMode.current as "case" | "csv");
      restoredMode.current = null;
    }
  }, [restored, caseId]);

  useEffect(() => {
    try {
      sessionStorage.setItem(
        SESSION_KEY,
        JSON.stringify({ analysisId: result?.analysis_id ?? null, mode, caseId, csv, analyst, note, amountFormat }),
      );
    } catch {
      /* storage unavailable — reload restore just won't work */
    }
  }, [result, mode, caseId, csv, analyst, note, amountFormat]);

  const run = async () => {
    setRunning(true);
    setError("");
    setResult(null);
    setDecisions([]);
    setVerify(null);
    setWall(null);
    setStages([]);
    setHlEv("");
    setHlTx("");
    setRestored("");
    stagesRef.current = [];
    const payload =
      mode === "case"
        ? { case_id: caseId!, llm_draft: wantLlm }
        : { csv_text: csv || SAMPLE_CSV, amount_format: amountFormat, llm_draft: wantLlm };
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

  const analystOk = analyst.trim().length >= 2;
  const noteOk = note.trim().length >= 10;

  const decide = async (d: string) => {
    if (!result || !analystOk || !noteOk) return;
    const r = await sendDecision({
      analysis_id: result.analysis_id,
      decision: d,
      analyst: analyst.trim(),
      note: note.trim(),
    });
    if (r.ok) {
      const rec = await getAnalysis(result.analysis_id);
      if (rec) setDecisions(rec.decisions);
      setToast(`Recorded on the server: ${d} · ${result.case_id} · ${result.analysis_id.slice(0, 11)}…`);
    } else {
      setToast(`Decision NOT recorded: ${r.error}`);
    }
    setTimeout(() => setToast(""), 4000);
    onDecided();
  };

  const badCites = useMemo(() => new Set(result?.narrative_check.invalid_citations ?? []), [result]);
  const badDraftCites = useMemo(
    () => new Set(result?.llm_draft?.check?.invalid_citations ?? []),
    [result],
  );

  const doExport = async () => {
    if (!result || exporting) return;
    setExporting(true);
    setVerify(null);
    try {
      const bundle = await exportBundle(result.analysis_id);
      const v = await verifyBundle(bundle);
      setVerify(v);
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `dalil-export-${result.case_id}-${result.analysis_id.slice(3, 11)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setToast(e instanceof Error ? e.message : String(e));
      setTimeout(() => setToast(""), 5000);
    } finally {
      setExporting(false);
    }
  };

  const evidById = useMemo(() => {
    const m = new Map<string, { text: string; kind: string; ref: string }>();
    result?.evidence.forEach((e) => m.set(e.id, e));
    return m;
  }, [result]);

  const focusTx = (txId: string) => {
    setHlTx(txId);
    requestAnimationFrame(() =>
      document.getElementById(`tx-${txId}`)?.scrollIntoView({ behavior: "smooth", block: "center" }),
    );
  };

  const focusEvidence = (id: string) => {
    setHlEv(id);
    const e = evidById.get(id);
    if (e && e.kind === "transaction") focusTx(e.ref);
    else setHlTx("");
  };

  const selectedCase = cases.find((c) => c.case_id === caseId);
  const draft = result?.llm_draft ?? null;

  return (
    <>
      <div className="title-line">
        <h2>Investigate</h2>
        <span className="muted small">
          pick a synthetic demo case, or paste/upload a new CSV — the pipeline runs live on the server
        </span>
        {restored && (
          <span className="badge neutral" title="analysis_id kept in this tab; result re-fetched from the server">
            {restored}
          </span>
        )}
        <div className="sep" />
        {result && (
          <span className="muted small mono" title={`input sha256 ${result.input_sha256}`}>
            {result.analysis_id.slice(0, 15)}… · {result.model_version} · {result.total_ms} ms
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
                New CSV
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
                  placeholder="ts,amount,direction,counterparty_name,counterparty_kind,channel,memo"
                  value={csv}
                  onChange={(e) => setCsv(e.target.value)}
                />
                <div className="center" style={{ marginTop: 8, gap: 8, flexWrap: "wrap" }}>
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
                  <label className="small muted">
                    amount format{" "}
                    <select
                      value={amountFormat}
                      onChange={(e) => setAmountFormat(e.target.value)}
                      style={{ width: "auto", display: "inline-block" }}
                    >
                      <option value="strict">strict — reject ambiguous “4,500”</option>
                      <option value="dot-thousands">1.234.567,89 (dot = thousands)</option>
                      <option value="comma-thousands">1,234,567.89 (comma = thousands)</option>
                    </select>
                  </label>
                </div>
                <div className="small muted" style={{ marginTop: 6 }}>
                  Required columns: ts, amount, direction, counterparty_name. Dates ISO, dd.mm.yyyy or
                  dd/mm/yyyy, not after today. Amounts like “43 500 000” or “4,5 млн”. Bad rows are
                  rejected with row numbers — never silently changed. Subject metadata is not invented:
                  if missing, the model input is imputed and the result is marked provisional.
                </div>
              </>
            )}
            <label className="small muted" style={{ display: "block", marginTop: 10 }}>
              <input type="checkbox" checked={wantLlm} onChange={(e) => setWantLlm(e.target.checked)} /> also
              generate the experimental local-LLM draft (slow on CPU)
            </label>
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
                <div key={s.stage} className={`stage ${s.status}`} title={s.detail || ""}>
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
              {!stages.length && <div className="muted small">no run in this tab yet</div>}
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
            {result && !!result.input_summary.warnings?.length && (
              <div className="note warn" style={{ marginTop: 8 }}>
                {result.input_summary.warnings!.map((w, i) => (
                  <div key={i}>⚠ {w}</div>
                ))}
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
                typology rule hits with evidence, a template note assembled from that evidence, an
                optional experimental LLM draft, and the analyst decision / export flow.
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
                  <span className="hint">deterministic layer · click a tx id to jump to it</span>
                </h3>
                <div className="scen">
                  {result.scenarios.map((s) => (
                    <div key={s.code} className={`scen-row ${s.matched ? "hit" : ""}`}>
                      <div className="scen-head">
                        <span className="code">{s.code}</span>
                        <span>{s.name}</span>
                        <span className="sep" />
                        <span className={`badge ${s.matched ? "high" : "neutral"}`}>
                          {s.matched
                            ? `hit · sev ${s.severity.toFixed(2)}`
                            : s.detail.startsWith("NOT EVALUATED")
                              ? "not evaluated"
                              : "no match"}
                        </span>
                      </div>
                      <div className="scen-detail">
                        {s.detail}
                        {s.name_uz && <span className="muted"> · uz: {s.name_uz}</span>}
                      </div>
                      {s.matched && s.evidence.length > 0 && (
                        <div className="txrefs">
                          {s.evidence.map((t) => (
                            <span key={t} className="txref" onClick={() => focusTx(t)}>
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
                  <span className="hint">template — assembled only from the evidence list · no LLM</span>
                </h3>
                <div className="narrative">
                  {renderNarrative(result.narrative, badCites, focusEvidence)}
                </div>
                <CheckBadges check={result.narrative_check} />
              </div>

              <div className="card">
                <h3>
                  Experimental local-LLM draft
                  <span className="hint">
                    {draft
                      ? draft.status === "unavailable"
                        ? "LLM offline — no draft; the template note above is unaffected"
                        : `${draft.model} · ${(draft.latency_ms / 1000).toFixed(1)} s · not the record`
                      : "not requested for this run"}
                  </span>
                </h3>
                {draft && draft.status === "truncated" && (
                  <div className="note err" style={{ marginBottom: 8 }}>
                    INCOMPLETE DRAFT — generation stopped at the token limit. Do not rely on it.
                  </div>
                )}
                {draft && draft.status !== "unavailable" && (
                  <>
                    <div className="note warn small" style={{ marginBottom: 8 }}>
                      Experimental: a small local model can mis-state direction, typology or which
                      evidence supports a claim. Only the checks below are automated.
                    </div>
                    <div className="narrative">{renderNarrative(draft.text, badDraftCites, focusEvidence)}</div>
                    {draft.check && <CheckBadges check={draft.check} />}
                  </>
                )}
              </div>

              <div className="grid-3">
                <div className="card">
                  <h3>
                    Evidence
                    <span className="hint">click: show source transaction</span>
                  </h3>
                  <div className="evi-list">
                    {result.evidence.map((e) => (
                      <div
                        key={e.id}
                        className={`evi ${hlEv === e.id || (hlTx !== "" && e.ref === hlTx) ? "hl" : ""}`}
                        onClick={() => focusEvidence(e.id)}
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
                  <label className="small muted">
                    Analyst name (self-declared — not an authenticated identity)
                    <input
                      type="text"
                      value={analyst}
                      placeholder="e.g. Synthetic QA"
                      onChange={(e) => setAnalyst(e.target.value)}
                      style={{ marginTop: 4 }}
                    />
                  </label>
                  <textarea
                    rows={3}
                    style={{ marginTop: 8 }}
                    placeholder="justification (required, ≥10 characters)"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                  <div className="decisions" style={{ marginTop: 8 }}>
                    {(
                      [
                        ["dismiss", "Dismiss", "good"],
                        ["escalate", "Escalate L2", "warn"],
                        ["file_str", "File STR", "danger"],
                        ["request_info", "Request info", "ghost"],
                      ] as const
                    ).map(([d, label, cls]) => (
                      <button
                        key={d}
                        className={`btn ${cls} sm`}
                        disabled={!analystOk || !noteOk}
                        title={!analystOk || !noteOk ? "enter analyst name and justification first" : ""}
                        onClick={() => decide(d)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <div className="small muted" style={{ marginTop: 8 }}>
                    Stored on the server against this analysis ({result.analysis_id.slice(0, 11)}…)
                    with the input hash; the score and checks come from the server record.
                  </div>
                  {decisions.length > 0 && (
                    <div className="note ok small" style={{ marginTop: 8 }}>
                      {decisions.map((d, i) => (
                        <div key={i}>
                          ✓ {d.decision} · {d.analyst} · {d.ts.slice(0, 19).replace("T", " ")} UTC — “{d.note}”
                        </div>
                      ))}
                    </div>
                  )}
                  <div style={{ marginTop: 10 }}>
                    <button className="btn ghost sm" disabled={exporting || running} onClick={doExport}>
                      {exporting ? "Exporting…" : "Export package (.json)"}
                    </button>
                  </div>
                  {verify && (
                    <div className={`note ${verify.integrity_ok && verify.server_record.status === "match" ? "ok" : "err"} small`} style={{ marginTop: 8 }}>
                      <div>
                        Integrity (hashes recomputed): {verify.integrity_ok ? "consistent" : "MISMATCH"}
                      </div>
                      <div>Matches this server&apos;s record: {verify.server_record.status}</div>
                      {[...verify.problems, ...verify.server_record.problems].map((p, i) => (
                        <div key={i}>⚠ {p}</div>
                      ))}
                    </div>
                  )}
                  <div className="small muted" style={{ marginTop: 6 }}>
                    SHA-256 detects later edits only while the original hashes are trusted — not a
                    signature. To check an edited file: <span className="mono">python scripts/verify_export.py file.json</span>
                  </div>
                </div>
              </div>

              <div className="card">
                <h3>
                  Transactions
                  <span className="hint">
                    {mode === "case" && selectedCase ? selectedCase.subject_name : "CSV input"} · highlighted
                    row = selected evidence
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
                          <tr key={t.id} className={hlTx === t.id ? "hl" : ""} id={`tx-${t.id}`}>
                            <td>{t.id}</td>
                            <td>{t.ts}</td>
                            <td style={{ color: t.direction === "in" ? "var(--low)" : "var(--high)" }}>
                              {t.direction}
                            </td>
                            <td>
                              {t.amount.toLocaleString("en-US", { maximumFractionDigits: 2 })}
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

      {hlEv && evidById.has(hlEv) && (
        <div className="toast" style={{ maxWidth: 420 }}>
          <b>{hlEv}</b> — {evidById.get(hlEv)!.text}
        </div>
      )}
      {toast && <div className="toast">{toast}</div>}
    </>
  );
}
