export interface ScenarioHit {
  code: string;
  name: string;
  name_uz: string;
  matched: boolean;
  severity: number;
  detail: string;
  evidence: string[];
}

export interface EvidenceItem {
  id: string;
  kind: string;
  text: string;
  ref: string;
}

export interface StageTiming {
  stage: string;
  ms: number;
}

export interface NarrativeCheck {
  citation_precision: number; // share of [E#] ids that exist
  checked_citations: number;
  invalid_citations: string[];
  unverified_numbers: string[];
  numbers_checked: number;
  numbers_supported: number;
  unsupported_numbers: string[];
  miscited_numbers: string[];
  uncited_numbers: string[];
  numeric_consistency: number | null;
  complete: boolean;
  semantics: "not_verified";
  status: "consistent" | "issues";
  mode: "llm" | "deterministic";
}

export interface LlmDraft {
  status: "complete" | "truncated" | "unavailable";
  text: string;
  check: NarrativeCheck | null;
  latency_ms: number;
  model: string;
  finish_reason?: string;
  error?: string;
}

export interface AnalysisResult {
  case_id: string;
  score: number;
  risk_band: "low" | "medium" | "high" | "critical";
  decision_hint: string;
  suspicious: boolean;
  features: Record<string, number>;
  top_features: {
    feature: string;
    value: number;
    display: string;
    impact: number;
    baseline: number;
  }[];
  scenarios: ScenarioHit[];
  evidence: EvidenceItem[];
  narrative: string;
  narrative_check: NarrativeCheck;
  timings: StageTiming[];
  total_ms: number;
  model_version: string;
  analysis_id: string;
  input_sha256: string;
  llm_draft: LlmDraft | null;
  transactions: {
    id: string; ts: string; amount: number; direction: string;
    from_name: string; to_name: string; channel: string; memo: string;
    from_kind: string; to_kind: string;
  }[];
  input_summary: Record<string, unknown> & {
    n_tx?: number;
    n_counterparty_clusters?: number;
    merged_identity_groups?: string[][];
    ml_probability?: number;
    rule_component?: number;
    ml_weight?: number;
    rule_weight?: number;
    warnings?: string[];
    imputed?: Record<string, number>;
    amount_format?: string;
  };
}

export interface StageEvent {
  stage: string;
  status: "running" | "done";
  detail?: string;
  ms?: number;
}

export interface QueueCase {
  case_id: string;
  subject_name: string;
  subject_kind: string;
  branch: string;
  opened_at: string;
  n_tx: number;
  score: number | null;
  risk_band: string | null;
  scenarios: string[];
}

export interface CaseOption {
  case_id: string;
  subject_name: string;
  subject_kind: string;
  n_tx: number;
  opened_at: string;
  branch: string;
}

export interface Health {
  status: string;
  model_version: string;
  llm: { available: boolean; base_url: string; model: string; error?: string };
  queue_size: number;
  audit_entries: number;
}

export interface AuditEntry {
  ts: string;
  case_id: string;
  score: number;
  decision: string;
  analyst: string;
  note: string;
  model_version: string;
  analysis_id?: string;
  input_sha256?: string;
  result_sha256?: string;
}

export interface StoredAnalysis {
  result: AnalysisResult;
  input_sha256: string;
  result_sha256: string;
  created_at: string;
  decisions: AuditEntry[];
}

export interface VerifyResult {
  ok: boolean;
  integrity_ok: boolean;
  problems: string[];
  server_record: { status: "match" | "mismatch" | "not_found" | "no_analysis_id"; problems: string[] };
}
