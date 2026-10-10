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
    channel: Literal["p2p", "cash_in", "cash_out", "atm", "card", "pos", "merchant", "wire"] = "p2p"
    memo: str = ""
    phone: str = ""
    geo: str = ""


class CaseRecord(BaseModel):
    """An alert case: subject account plus the transaction window under review."""

    case_id: str
    subject_account: str
    subject_name: str
    subject_kind: Literal["person", "business"] = "person"
    account_age_days: int = 400
    declared_turnover_monthly: float = 0.0
    branch: str = ""
    alert_source: str = "scenario-engine"
    opened_at: str = ""
    transactions: list[Transaction]
    labels: list[str] = Field(default_factory=list)  # ground truth (generated data only)
    is_suspicious: bool = False
    split: str = "demo"
    generator_variant: str = "base"  # base | novel (held-out pattern variants)


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
    citation_precision: float
    checked_citations: int
    invalid_citations: list[str] = Field(default_factory=list)
    unverified_numbers: list[str] = Field(default_factory=list)
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


class DecisionIn(BaseModel):
    case_id: str
    decision: Literal["dismiss", "escalate", "file_str", "request_info"]
    analyst: str = "demo-analyst"
    note: str = ""


class AuditEntry(BaseModel):
    ts: str
    case_id: str
    score: float
    decision: str
    analyst: str
    note: str = ""
    narrative_check: dict[str, Any] = Field(default_factory=dict)
    model_version: str = ""


class AnalyzeRequest(BaseModel):
    """Jury/custom input: either a known case id or raw CSV text."""

    case_id: str | None = None
    csv_text: str | None = None
    case_name: str | None = None
