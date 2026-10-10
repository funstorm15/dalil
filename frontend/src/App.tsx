import { useCallback, useEffect, useState } from "react";
import { getHealth } from "./api";
import InvestigateView from "./components/InvestigateView";
import QueueView from "./components/QueueView";
import SystemView from "./components/SystemView";
import type { Health } from "./types";

type Tab = "queue" | "investigate" | "system";

export default function App() {
  const [tab, setTab] = useState<Tab>("queue");
  const [health, setHealth] = useState<Health | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const refresh = useCallback(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
  }, [refresh]);

  const openCase = (id: string) => {
    setSelected(id);
    setTab("investigate");
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>DALIL</h1>
          <span className="sub">AML investigation copilot · MKBANK FCC — alert investigation desk</span>
        </div>
        <nav className="tabs">
          <button className={`tab ${tab === "queue" ? "active" : ""}`} onClick={() => setTab("queue")}>
            Alert queue
          </button>
          <button
            className={`tab ${tab === "investigate" ? "active" : ""}`}
            onClick={() => setTab("investigate")}
          >
            Investigate
          </button>
          <button className={`tab ${tab === "system" ? "active" : ""}`} onClick={() => setTab("system")}>
            System & evidence
          </button>
        </nav>
        <div className="pill" title={health ? `model ${health.model_version}` : "backend unreachable"}>
          <span className={`dot ${health?.llm?.available ? "" : "off"}`} />
          {health
            ? health.llm.available
              ? `local LLM · ${health.llm.model}`
              : "LLM offline · deterministic mode"
            : "backend offline"}
        </div>
      </header>

      <main className="page">
        {tab === "queue" && <QueueView onOpen={openCase} />}
        {tab === "investigate" && (
          <InvestigateView caseId={selected} onCaseChange={setSelected} onDecided={refresh} />
        )}
        {tab === "system" && <SystemView />}
      </main>
    </div>
  );
}
