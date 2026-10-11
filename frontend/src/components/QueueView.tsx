import { useEffect, useState } from "react";
import { getAudit, getQueue } from "../api";
import type { AuditEntry, QueueCase } from "../types";

const BAND_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

function bandColor(band: string | null): string {
  switch (band) {
    case "critical":
      return "var(--critical)";
    case "high":
      return "var(--high)";
    case "medium":
      return "var(--medium)";
    default:
      return "var(--low)";
  }
}

export default function QueueView({ onOpen }: { onOpen: (id: string) => void }) {
  const [cases, setCases] = useState<QueueCase[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [err, setErr] = useState("");
  const [sort, setSort] = useState<"score" | "time">("score");

  useEffect(() => {
    getQueue()
      .then(setCases)
      .catch((e) => setErr(String(e)));
    getAudit().then(setAudit).catch(() => undefined);
  }, []);

  const rows = [...cases].sort((a, b) => {
    if (sort === "time") return (b.opened_at || "").localeCompare(a.opened_at || "");
    const ba = BAND_ORDER[a.risk_band ?? "low"] ?? 4;
    const bb = BAND_ORDER[b.risk_band ?? "low"] ?? 4;
    if (ba !== bb) return ba - bb;
    return (b.score ?? 0) - (a.score ?? 0);
  });

  const counts = {
    critical: cases.filter((c) => c.risk_band === "critical").length,
    high: cases.filter((c) => c.risk_band === "high").length,
    medium: cases.filter((c) => c.risk_band === "medium").length,
    low: cases.filter((c) => c.risk_band === "low").length,
  };

  return (
    <>
      <div className="title-line">
        <h2>Alert queue</h2>
        <span className="muted small">
          pre-scored demo cases — click a row to open the investigation workspace
        </span>
        <div className="sep" />
        <div className="chips">
          <span className="badge critical">{counts.critical} critical</span>
          <span className="badge high">{counts.high} high</span>
          <span className="badge medium">{counts.medium} medium</span>
          <span className="badge low">{counts.low} low</span>
          <button className="btn ghost sm" onClick={() => setSort(sort === "score" ? "time" : "score")}>
            sort: {sort === "score" ? "risk" : "newest"}
          </button>
        </div>
      </div>

      {err && <div className="note err">Backend unreachable: {err}</div>}

      <div className="grid2 queue-layout">
        <div className="card queue-table">
          <table className="q">
            <thead>
              <tr>
                <th>Case</th>
                <th>Subject</th>
                <th>Branch</th>
                <th>Txns</th>
                <th>Rules hit</th>
                <th style={{ width: 180 }}>DALIL score</th>
                <th>Band</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.case_id} onClick={() => onOpen(c.case_id)}>
                  <td className="mono"><button className="case-link" onClick={(event) => { event.stopPropagation(); onOpen(c.case_id); }}>{c.case_id}</button></td>
                  <td>
                    {c.subject_name}{" "}
                    <span className="muted small">({c.subject_kind})</span>
                  </td>
                  <td>{c.branch}</td>
                  <td className="mono">{c.n_tx}</td>
                  <td className="mono small">{c.scenarios.join(" ") || "—"}</td>
                  <td>
                    <div className="center">
                      <div className="scorebar" style={{ flex: 1 }}>
                        <i
                          style={{
                            width: `${c.score ?? 0}%`,
                            background: bandColor(c.risk_band),
                          }}
                        />
                      </div>
                      <span className="mono" style={{ width: 38, textAlign: "right" }}>
                        {c.score ?? "—"}
                      </span>
                    </div>
                  </td>
                  <td>
                    <span className={`badge ${c.risk_band ?? "neutral"}`}>{c.risk_band}</span>
                  </td>
                </tr>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={7} className="muted">
                    {err ? "—" : "loading…"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="card">
            <h3>Human-in-the-loop</h3>
            <div className="note">
              DALIL ranks and drafts; <b>the analyst decides</b> (name is self-declared, not
              authenticated). Each decision is appended to a JSONL decision log on the server, bound
              to the analysis_id and input hash, with the server-side score and note-check result.
              The log is an ordinary file — not tamper-proof.
            </div>
            <div style={{ marginTop: 10 }} className="small muted">
              Recent decisions on this server: <b>{audit.length}</b>
            </div>
            <div className="evi-list" style={{ marginTop: 8, maxHeight: 240 }}>
              {audit.map((a, i) => (
                <div className="evi" key={i}>
                  <span className="id">{a.case_id}</span>
                  <span>
                    <b>{a.decision}</b> · score {a.score} · {a.analyst}
                    {a.note ? ` — “${a.note}”` : ""}
                  </span>
                </div>
              ))}
              {!audit.length && <div className="muted small">no decisions recorded yet</div>}
            </div>
          </div>
          <div className="card">
            <h3>
              Why this queue exists
              <span className="hint">the cost we remove</span>
            </h3>
            <div className="small muted" style={{ lineHeight: 1.7 }}>
              Analysts inspect transactions, check counterparties and document the reasons for a decision.
              DALIL organises evidence and prepares a template note for review.
              Time savings and alert volumes are pilot assumptions, not measured bank outcomes.
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
