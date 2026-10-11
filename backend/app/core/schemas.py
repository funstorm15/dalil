"""Shared pydantic schemas for the DALIL pipeline and API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Transaction(BaseModel):
    """A single payment event, normalized from casebook/CSV/jury input."""

    id: str
    ts: str  # ISO-8601
    amount: float  # UZS
    direction: Literal["in", "out"]
    from_account: str
    from_name: str
    from_kind: Literal["person", "business", "subject"] = "person"
    to_account: str
    to_name: str
    to_kind: Literal["person", "business", "subject"] = "person"
    channel: Literal["p2p", "cash_in", "cash_out", "atm", "card", "pos", "merchant", "wire", "unknown"] = "p2p"
    memo: str = ""
    phone: str = ""
    geo: str = ""


class CaseRecord(BaseModel):
    """An alert case: subject account plus the transaction window under review."""

    case_id: str
    subject_account: str
    subject_name: str
    subject_kind: Literal["person", "business"] = "person"
    account_age_days: int | None = None  # None = not provided (never invented)
    declared_turnover_monthly: float | None = None
    branch: str = ""
    alert_source: str = "scenario-engine"
    opened_at: str = ""
    transactions: list[Transaction]
    labels: list[str] = Field(default_factory=list)  # ground truth (generated data only)
    is_suspicious: bool = False
    split: str = "demo"
    generator_variant: str = "base"  # base | novel (held-out pattern variants)
    input_notes: list[str] = Field(default_factory=list)  # non-fatal input caveats
    amount_format: str = "strict"


class ScenarioHit(BaseModel):
    code: str
    name: str
    name_uz: str = ""
    matched: bool
    severity: float = 0.0  # 0..1
    detail: str = ""
    evidence: list[str] = Field(default_factory=list)  # transaction ids


class FeatureRow(BaseModel):
    features: dict[str, float]


class EvidenceItem(BaseModel):
    """One citable fact handed to the LLM and checked afterwards."""

    id: str  # E1, E2, ...
    kind: str  # feature | scenario | transaction | subject
    text: str
    ref: str = ""  # tx id / feature key


class StageTiming(BaseModel):
    stage: str
    ms: float


class NarrativeCheck(BaseModel):
    """Separate statuses — see core/verifier.py. Meaning is never machine-verified."""

    citation_precision: float  # share of [E#] ids that exist in the evidence pack
    checked_citations: int
    invalid_citations: list[str] = Field(default_factory=list)
    unverified_numbers: list[str] = Field(default_factory=list)  # union of the three lists below
    numbers_checked: int = 0  # numbers + amounts + ISO dates found in the note
    numbers_supported: int = 0  # matched a value in evidence cited in the same sentence
    unsupported_numbers: list[str] = Field(default_factory=list)  # in no evidence item
    miscited_numbers: list[str] = Field(default_factory=list)  # only in non-cited evidence
    uncited_numbers: list[str] = Field(default_factory=list)  # sentence has no citation
    numeric_consistency: float | None = None  # supported / checked
    complete: bool = True  # False when generation hit the token limit
    semantics: Literal["not_verified"] = "not_verified"
    status: Literal["consistent", "issues"] = "issues"
    mode: Literal["llm", "deterministic"] = "llm"


class AnalysisResult(BaseModel):
    case_id: str
    score: float  # 0..100
    risk_band: Literal["low", "medium", "high", "critical"]
    decision_hint: str
    suspicious: bool
    features: dict[str, float]
    top_features: list[dict[str, Any]]
    scenarios: list[ScenarioHit]
    evidence: list[EvidenceItem]
    narrative: str
    narrative_check: NarrativeCheck
    timings: list[StageTiming]
    total_ms: float
    model_version: str
    transactions: list[dict[str, Any]] = Field(default_factory=list)
    input_summary: dict[str, Any]
    # experimental local-LLM draft (text, status, check, latency) — never the primary note
    llm_draft: dict[str, Any] | None = None
    # server-side identity of THIS analysis run (set by the API, see core/store.py)
    analysis_id: str = ""
    input_sha256: str = ""


class DecisionIn(BaseModel):
    """Analyst decision on ONE stored analysis. The analyst name is self-declared
    (typed by the user) — it is not an authenticated identity."""

    analysis_id: str = Field(min_length=8, max_length=64)
    decision: Literal["dismiss", "escalate", "file_str", "request_info"]
    analyst: str = Field(min_length=2, max_length=80)
    note: str = Field(min_length=10, max_length=2000)  # justification, required


class AuditEntry(BaseModel):
    ts: str
    case_id: str
    score: float
    decision: str
    analyst: str  # self-declared name, not authenticated
    note: str = ""
    narrative_check: dict[str, Any] = Field(default_factory=dict)
    model_version: str = ""
    analysis_id: str = ""
    input_sha256: str = ""
    result_sha256: str = ""


class AnalyzeRequest(BaseModel):
    """Jury/custom input: either a known case id or raw CSV text."""

    case_id: str | None = None
    csv_text: str | None = None
    amount_format: Literal["strict", "dot-thousands", "comma-thousands"] = "strict"
    llm_draft: bool = True  # also request the experimental local-LLM draft
