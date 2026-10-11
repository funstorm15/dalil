import { useCallback, useEffect, useState } from "react";
import { getHealth } from "./api";
import InvestigateView from "./components/InvestigateView";
import QueueView from "./components/QueueView";
import SystemView from "./components/SystemView";
import type { Health } from "./types";

type Tab = "queue" | "investigate" | "system";
type Theme = "light" | "dark";
const THEME_KEY = "dalil:development-v2:theme";

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const saved = localStorage.getItem(THEME_KEY);
      if (saved === "light" || saved === "dark") return saved;
    } catch { /* Storage can be unavailable in private browser contexts. */ }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(THEME_KEY, theme); } catch { /* Switching still works without storage. */ }
  }, [theme]);

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
          <h1>DALIL <span className="version-label">V2 · Casebook</span></h1>
          <span className="sub">
            AML investigation copilot · synthetic demo · MKBANK: proposed pilot client
          </span>
        </div>

        <div className="pill" title={health ? `model ${health.model_version}` : "backend unreachable"}>
          <span className={`dot ${health?.llm?.available ? "" : "off"}`} />
          {health
            ? health.llm.available
              ? `local LLM up · ${health.llm.model} (experimental drafts)`
              : "LLM offline · template note only"
            : "backend offline"}
        </div>
        <button
          className="btn ghost theme-toggle"
          type="button"
          aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
          onClick={() => setTheme(theme === "light" ? "dark" : "light")}
        >
          {theme === "light" ? "Dark mode" : "Light mode"}
        </button>
      </header>

      <div className="workspace">
        <aside className="sidebar">
          <div className="sidebar-label">CASEBOOK / 02</div>
        <nav className="tabs" aria-label="Main navigation">
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
          <div className="sidebar-note">Evidence first.<br />Human judgment always.<span>Synthetic demonstration</span></div>
        </aside>
      <main className="page">
        {tab === "queue" && <QueueView onOpen={openCase} />}
        {tab === "investigate" && (
          <InvestigateView caseId={selected} onCaseChange={setSelected} onDecided={refresh} />
        )}
        {tab === "system" && <SystemView />}
      </main>
      </div>
    </div>
  );
}
