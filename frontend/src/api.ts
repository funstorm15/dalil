import type {
  AnalysisResult,
  AuditEntry,
  CaseOption,
  Health,
  QueueCase,
  StageEvent,
} from "./types";

export async function getHealth(): Promise<Health> {
  const r = await fetch("/api/health");
  if (!r.ok) throw new Error("health failed");
  return r.json();
}

export async function getQueue(): Promise<QueueCase[]> {
  const r = await fetch("/api/queue?limit=80");
  if (!r.ok) throw new Error("queue failed");
  const d = await r.json();
  return d.cases;
}

export async function getCases(): Promise<CaseOption[]> {
  const r = await fetch("/api/cases");
  if (!r.ok) throw new Error("cases failed");
  const d = await r.json();
  return d.cases;
}

export async function getAudit(): Promise<AuditEntry[]> {
  const r = await fetch("/api/audit?limit=30");
  if (!r.ok) return [];
  const d = await r.json();
  return d.entries;
}

export async function getMetrics(): Promise<Record<string, any>> {
  const r = await fetch("/api/metrics");
  if (!r.ok) return {};
  return r.json();
}

export async function getSystem(): Promise<Record<string, any>> {
  const r = await fetch("/api/system");
  if (!r.ok) return {};
  return r.json();
}

export interface AnalyzeHandlers {
  onStage: (ev: StageEvent) => void;
  onResult: (res: AnalysisResult) => void;
  onError: (msg: string) => void;
  onDone?: (wallMs: number) => void;
}

/** POST /api/analyze and consume the SSE stream (stage events live). */
export async function analyze(
  payload: { case_id?: string; csv_text?: string },
  h: AnalyzeHandlers,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    h.onError(String(e));
    return;
  }
  if (!res.ok || !res.body) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      msg = j.detail || msg;
    } catch {
      /* ignore */
    }
    h.onError(msg);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const lines = chunk.split("\n");
      let event = "message";
      let data = "";
      for (const ln of lines) {
        if (ln.startsWith("event:")) event = ln.slice(6).trim();
        else if (ln.startsWith("data:")) data += ln.slice(5).trim();
      }
      if (!data) continue;
      try {
        const parsed = JSON.parse(data);
        if (event === "stage") h.onStage(parsed as StageEvent);
        else if (event === "result") h.onResult(parsed as AnalysisResult);
        else if (event === "error") h.onError(parsed.error || "stream error");
        else if (event === "done" && h.onDone) h.onDone(parsed.wall_ms);
      } catch {
        /* partial frame */
      }
    }
  }
}

export async function sendDecision(payload: {
  decision: { case_id: string; decision: string; analyst?: string; note?: string };
  result?: unknown;
}): Promise<boolean> {
  const r = await fetch("/api/decision/full", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return r.ok;
}

export const SAMPLE_CSV = `ts,amount,direction,counterparty_name,counterparty_kind,channel,memo
05.04.2026 10:12,"43 500 000",in,Abdurahmon Karimov,person,cash_in,
12.04.2026 11:40,47800000,in,Dilnoza Yusupova,person,cash_in,
19.04.2026 09:55,"46 200 000",in,Sardor Tursunov,person,p2p,qarz
26.04.2026 14:03,44100000,in,Gulbahor Rahimov,person,cash_in,
03.05.2026 16:20,"45 000 000",in,Jasur Mamatov,person,p2p,
10.05.2026 12:08,48900000,in,Nodira Xolmatova,person,cash_in,
17.05.2026 10:31,"42 750 000",in,Otabek Ergashev,person,p2p,perevod
24.05.2026 15:47,45600000,in,Sherzod Nazarov,person,cash_in,
31.05.2026 11:19,"47 100 000",in,Zilola Ismailova,person,p2p,
07.06.2026 13:02,44400000,in,Farhod Qodirov,person,cash_in,
14.06.2026 17:26,"280 000 000",out,Savdo Markaz MChJ,business,wire,tovar
21.06.2026 10:44,"150 000 000",out,Aleksandr Petrov,person,p2p,`;
