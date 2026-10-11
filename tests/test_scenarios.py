"""Challenge scenarios: bad input, ambiguity, thin data, LLM down, persistence.

Process-level assertions only for the legal-cash-business fixture — the model
is not fitted or tuned against these examples.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
sys.path.insert(0, str(ROOT / "backend"))

from app.core.export import build_export, verify_bundle  # noqa: E402
from app.core.features import build_entity_clusters  # noqa: E402
from app.core.ingest import InputValidationError, case_from_csv  # noqa: E402
from app.core.llm import LLMClient  # noqa: E402
from app.core.pipeline import analyze  # noqa: E402
from app.core.scenarios import RULESET_VERSION  # noqa: E402
from app.core.schemas import EvidenceItem  # noqa: E402
from app.core.verifier import verify_narrative  # noqa: E402

DEAD_LLM = LLMClient(base_url="http://127.0.0.1:1/v1", model="none")


# ---------------- invalid amount / date ----------------
def test_bad_amount_and_date_rejected_with_row_messages():
    text = (FIXTURES / "bad_amount_date.csv").read_text(encoding="utf-8")
    with pytest.raises(InputValidationError) as ei:
        case_from_csv(text)
    errs = ei.value.errors
    assert len(errs) >= 4
    assert any(e.startswith("row 1") and "amount" in e for e in errs)
    assert any(e.startswith("row 2") and "date" in e for e in errs)
    assert any(e.startswith("row 3") and "missing" in e for e in errs)
    assert any(e.startswith("row 4") and "date" in e for e in errs)
    # junk never silently becomes 0.0 / empty date
    assert not any("0.0" in e for e in errs)


def test_api_rejects_bad_csv_not_crash():
    from app.api import routes
    from fastapi.testclient import TestClient

    routes._llm = DEAD_LLM
    from app.main import app

    text = (FIXTURES / "bad_amount_date.csv").read_text(encoding="utf-8")
    with TestClient(app) as client:
        r = client.post("/api/analyze", json={"csv_text": text})
        assert r.status_code == 422
        assert "Input rejected" in r.json()["detail"]
        assert "row 1" in r.json()["detail"]
        # header-only file
        r2 = client.post("/api/analyze", json={"csv_text": "ts,amount,direction\n"})
        assert r2.status_code == 422
        assert "no data rows" in r2.json()["detail"]


# ---------------- ambiguous RU/UZ names ----------------
def test_ambiguous_names_no_unjustified_merge():
    text = (FIXTURES / "ambiguous_names.csv").read_text(encoding="utf-8")
    case = case_from_csv(text)
    cl = build_entity_clusters(case)
    # transliteration variants + same phone: one person, merge is justified
    assert cl["cp-0"] == cl["cp-1"]
    # "A. Kazlum" with two plausible full names in the case: no merge
    assert cl["cp-2"] != cl["cp-3"]
    assert cl["cp-2"] != cl["cp-4"]
    assert cl["cp-3"] != cl["cp-4"]
    # prefix-related distinct first names (Testveks / Testvekslong): no merge
    assert cl["cp-10"] != cl["cp-0"]
    # same business with/without corp suffix: merge is justified
    assert cl["cp-6"] == cl["cp-7"]
    # different businesses sharing a word: no merge
    assert cl["cp-8"] != cl["cp-6"]


# ---------------- insufficient data ----------------
def test_thin_history_and_missing_metadata_surface_warnings():
    text = (FIXTURES / "thin_case.csv").read_text(encoding="utf-8")
    case = case_from_csv(text)
    res, _ = analyze(case.model_dump(), llm=DEAD_LLM, want_narrative=False)
    w = res.input_summary["warnings"]
    assert any("only 4 transactions" in x for x in w)
    assert any("declared turnover not provided" in x for x in w)
    assert any("subject name not provided" in x for x in w)
    assert 0 <= res.score <= 100  # runs, but the caveats are explicit
    sc06 = next(s for s in res.scenarios if s.code == "SC-06")
    assert not sc06.matched and sc06.detail.startswith("NOT EVALUATED")


def test_single_transaction_case_still_analyses():
    csv_text = "ts,amount,direction,counterparty_name\n01.05.2026,1000000,in,Test Person\n"
    case = case_from_csv(csv_text)
    res, _ = analyze(case.model_dump(), llm=DEAD_LLM, want_narrative=False)
    assert any("only 1 transactions" in x for x in res.input_summary["warnings"])


# ---------------- LLM down ----------------
def test_llm_down_is_labelled_template_mode():
    path = ROOT / "data/generated/cases_demo.jsonl"
    if not path.exists():
        pytest.skip("generated demo data not present")
    raw = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    res, events = analyze(raw, llm=DEAD_LLM, want_narrative=True)
    assert res.narrative_check.mode == "deterministic"
    assert res.narrative.startswith("**1) SUMMARY** (template — assembled from evidence, no LLM)")
    assert res.llm_draft["status"] == "unavailable" and res.llm_draft["text"] == ""
    assert any("LLM unavailable" in str(e.get("detail", "")) for e in events)
    # the template note is still checked (checks are warnings, they do not block)
    assert res.narrative_check.checked_citations > 0
    assert res.narrative_check.status == "consistent"


# ---------------- missing evidence id + unsourced number ----------------
def test_missing_evidence_and_unsourced_number_flagged_and_exported():
    ev = [EvidenceItem(id="E1", kind="feature", text="total_in = 100.0 mln UZS")]
    check = verify_narrative("Structure of 777 000 000 UZS [E99] over [E1].", ev)
    assert "E99" in check.invalid_citations
    assert check.unverified_numbers
    # invalid citation drags precision below 1.0 — surfaced, not hidden
    assert check.citation_precision == 0.5  # share of [E#] ids that exist
    # flags travel with the export package
    result = {"case_id": "T-1", "score": 50.0, "narrative": "x", "narrative_check": check.model_dump()}
    bundle = build_export(input_payload={"kind": "csv_input", "payload": "raw"},
                          result=result, decision=None, ruleset_version=RULESET_VERSION)
    assert bundle["narrative"]["check"]["invalid_citations"] == ["E99"]
    assert bundle["narrative"]["check"]["unverified_numbers"]
    assert verify_bundle(bundle)["ok"]


# ---------------- decision persistence ----------------
def test_decision_survives_process_restart(tmp_path):
    from app.core import audit

    p = tmp_path / "audit.log"
    audit.record_decision(case_id="FX-PERSIST", score=81.5, decision="escalate",
                          analyst="a.azizov", note="fan-in + young account",
                          narrative_check={"mode": "deterministic"},
                          model_version="m1", path=p)
    audit._MEM.clear()  # simulate a fresh process: memory is gone, disk remains
    rows = audit.tail(10, path=p)
    assert rows and rows[0]["case_id"] == "FX-PERSIST"
    assert rows[0]["decision"] == "escalate"
    assert rows[0]["score"] == 81.5
    assert rows[0]["note"] == "fan-in + young account"


def test_decision_api_round_trip_then_export_carries_it(monkeypatch, tmp_path):
    from app import config
    from app.api import routes
    from app.main import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(config, "AUDIT_PATH", tmp_path / "audit.log")
    monkeypatch.setattr(config, "ANALYSES_DIR", tmp_path / "analyses")
    routes._llm = DEAD_LLM
    path = ROOT / "data/generated/cases_demo.jsonl"
    if not path.exists():
        pytest.skip("generated demo data not present")
    raw = json.loads(path.read_text(encoding="utf-8").splitlines()[0])

    with TestClient(app) as client:
        r = client.post("/api/analyze", json={"case_id": raw["case_id"], "llm_draft": False})
        result = next(json.loads(b.split("data: ", 1)[1]) for b in r.text.split("\n\n")
                      if b.startswith("event: result"))
        r = client.post("/api/decision", json={
            "analysis_id": result["analysis_id"], "decision": "dismiss",
            "analyst": "test analyst", "note": "explained source of funds"})
        assert r.status_code == 200 and r.json()["ok"]
        entries = client.get("/api/audit").json()["entries"]
        assert entries[0]["case_id"] == raw["case_id"]
        assert entries[0]["decision"] == "dismiss"
        assert entries[0]["analysis_id"] == result["analysis_id"]
        bundle = client.post("/api/export", json={"analysis_id": result["analysis_id"]}).json()
        assert bundle["decision"]["decision"] == "dismiss"
        assert client.post("/api/export/verify", json=bundle).json()["ok"]


# ---------------- legal cash business (process-only) ----------------
def test_legal_cash_business_runs_without_special_casing():
    raw = json.loads((FIXTURES / "legal_cash_business.json").read_text(encoding="utf-8"))
    res, _ = analyze(raw, llm=DEAD_LLM, want_narrative=False)
    # structural/process assertions only — no expected score or risk band
    assert 0 <= res.score <= 100
    assert len(res.scenarios) == 6
    assert res.evidence
    # metadata complete: nothing imputed, no metadata warnings
    assert res.input_summary["imputed"] == {}
    assert not any("not provided" in w for w in res.input_summary["warnings"])
    # rule specs: cash-ins all below the 43 mln structuring floor …
    sc01 = next(s for s in res.scenarios if s.code == "SC-01")
    assert not sc01.matched
    # … and inflow is within the declared turnover (900 mln/mo vs ~347 mln total)
    sc06 = next(s for s in res.scenarios if s.code == "SC-06")
    assert not sc06.matched
    print(f"[observed] legal cash business score={res.score} band={res.risk_band} "
          f"(recorded for the status log, not asserted)")
