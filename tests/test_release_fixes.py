"""Regression tests for the post-audit release fixes (11 Oct 2026).

Each test reproduces one audit finding: evidence counterparty, decision
mixing across CSV cases, client-supplied results, silent input substitution,
numeric note checks, truncated LLM drafts and analyst validation.
"""
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core import store  # noqa: E402
from app.core.export import SECTIONS, canonical_bytes  # noqa: E402
from app.core.ingest import InputValidationError, case_from_csv  # noqa: E402
from app.core.llm import LLMClient, LLMStats  # noqa: E402
from app.core.normalize import AmountFormatError, parse_amount_strict  # noqa: E402
from app.core.pipeline import analyze  # noqa: E402
from app.core.schemas import EvidenceItem  # noqa: E402
from app.core.verifier import verify_narrative  # noqa: E402

DEAD_LLM = LLMClient(base_url="http://127.0.0.1:1/v1", model="none")
HDR = "ts,amount,direction,counterparty_name,counterparty_kind,channel,memo\n"
CSV_A = HDR + ("01.05.2026 10:00,45 000 000,in,Aziza Rahimova,person,cash_in,\n"
               "02.05.2026 11:00,30 000 000,out,Bekzod Tursunov,person,p2p,qarz\n"
               "03.05.2026 12:00,47 000 000,in,Dilshod Aliyev,person,cash_in,\n")
CSV_B = HDR + ("05.05.2026 09:00,12 000 000,in,Kamola Yusupova,person,p2p,\n"
               "06.05.2026 10:00,9 000 000,out,Savdo Markaz MChJ,business,wire,tovar\n")


def _result(resp_text: str) -> dict:
    for block in resp_text.split("\n\n"):
        if block.startswith("event: result"):
            return json.loads(block.split("data: ", 1)[1])
    raise AssertionError(f"no result event: {resp_text[-300:]}")


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from app import config
    from app.api import routes
    from app.main import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(config, "AUDIT_PATH", tmp_path / "audit.log")
    monkeypatch.setattr(config, "ANALYSES_DIR", tmp_path / "analyses")
    routes._llm = DEAD_LLM
    with TestClient(app) as c:
        yield c


def _analyze_csv(client, text, **kw) -> dict:
    r = client.post("/api/analyze", json={"csv_text": text, "llm_draft": False, **kw})
    assert r.status_code == 200, r.text
    return _result(r.text)


def _decide(client, aid, decision="escalate", note="near-threshold cash inflows"):
    return client.post("/api/decision", json={"analysis_id": aid, "decision": decision,
                                              "analyst": "Dilnoza A.", "note": note})


# ---------------- 1. evidence counterparty ----------------
def test_evidence_names_counterparty_for_incoming_and_outgoing():
    case = case_from_csv(CSV_A, case_id="CSV-T")
    res, _ = analyze(case.model_dump(), llm=DEAD_LLM, want_narrative=False)
    tx_ev = {e.ref: e.text for e in res.evidence if e.kind == "transaction"}
    assert "from Aziza Rahimova via cash_in" in tx_ev["row-1"]  # incoming: sender
    assert "to Bekzod Tursunov via p2p" in tx_ev["row-2"]  # outgoing: recipient
    for text in tx_ev.values():
        assert "Subject account" not in text


def test_demo_evidence_matches_source_transactions():
    raw = json.loads((ROOT / "data/generated/cases_demo.jsonl").read_text().splitlines()[0])
    res, _ = analyze(raw, llm=DEAD_LLM, want_narrative=False)
    txs = {t["id"]: t for t in res.transactions}
    for e in res.evidence:
        if e.kind == "transaction":
            t = txs[e.ref]
            name = t["from_name"] if t["direction"] == "in" else t["to_name"]
            assert f" {name} via {t['channel']}" in e.text
            assert t["to_name" if t["direction"] == "in" else "from_name"] == raw["subject_name"]


# ---------------- 2. decisions are bound to one analysis ----------------
def test_decision_for_case_a_never_appears_in_export_of_case_b(client):
    a = _analyze_csv(client, CSV_A)
    assert _decide(client, a["analysis_id"]).status_code == 200
    b = _analyze_csv(client, CSV_B)
    assert a["case_id"] != b["case_id"] and a["case_id"].startswith("CSV-")
    bundle_b = client.post("/api/export", json={"analysis_id": b["analysis_id"]}).json()
    assert bundle_b["decision"] is None
    bundle_a = client.post("/api/export", json={"analysis_id": a["analysis_id"]}).json()
    assert bundle_a["decision"]["analysis_id"] == a["analysis_id"]
    assert bundle_a["decision"]["input_sha256"] == a["input_sha256"]


def test_reanalysis_of_same_or_modified_csv_gets_a_fresh_analysis(client):
    a1 = _analyze_csv(client, CSV_A)
    _decide(client, a1["analysis_id"])
    a2 = _analyze_csv(client, CSV_A)  # same text: same case id, NEW analysis
    assert a2["case_id"] == a1["case_id"] and a2["analysis_id"] != a1["analysis_id"]
    assert client.post("/api/export", json={"analysis_id": a2["analysis_id"]}).json()["decision"] is None
    mod = _analyze_csv(client, CSV_A.replace("45 000 000", "45 000 001"))
    assert mod["case_id"] != a1["case_id"] and mod["input_sha256"] != a1["input_sha256"]


def test_analysis_and_decision_survive_server_restart(monkeypatch, tmp_path):
    from app import config
    from app.api import routes
    from app.core import audit
    from app.main import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(config, "AUDIT_PATH", tmp_path / "audit.log")
    monkeypatch.setattr(config, "ANALYSES_DIR", tmp_path / "analyses")
    routes._llm = DEAD_LLM
    with TestClient(app) as c:
        a = _analyze_csv(c, CSV_A)
        _decide(c, a["analysis_id"], decision="file_str", note="structuring pattern documented")
    audit._MEM.clear()  # a new process has no memory — only disk
    with TestClient(app) as c:
        got = c.get(f"/api/analysis/{a['analysis_id']}").json()
        assert got["result"]["score"] == a["score"]
        assert got["decisions"][-1]["decision"] == "file_str"


# ---------------- 3. the server is the source of results ----------------
def test_export_ignores_client_result_and_decision_needs_known_analysis(client):
    a = _analyze_csv(client, CSV_A)
    forged = copy.deepcopy(a)
    forged["score"], forged["narrative"] = 1.0, "nothing to see [E1]"
    b = client.post("/api/export", json={"analysis_id": a["analysis_id"], "result": forged}).json()
    assert b["analysis"]["score"] == a["score"] and b["narrative"]["text"] == a["narrative"]
    assert client.post("/api/export", json={"result": forged}).status_code == 404
    r = client.post("/api/decision", json={"analysis_id": "an-" + "0" * 32, "decision": "dismiss",
                                           "analyst": "X Y", "note": "no such analysis exists"})
    assert r.status_code == 404
    r = client.post("/api/decision", json={"analysis_id": a["analysis_id"], "decision": "dismiss",
                                           "analyst": "X Y", "note": "client tries to set score",
                                           "score": 1.0, "narrative_check": {"status": "consistent"}})
    assert r.status_code == 200 and r.json()["entry"]["score"] == a["score"]
    assert client.post("/api/decision", json={"analysis_id": "../../etc/passwd", "decision": "dismiss",
                                              "analyst": "X Y", "note": "path traversal attempt"}
                       ).status_code == 404


def _rehash(bundle: dict) -> dict:
    h = {n: hashlib.sha256(canonical_bytes(bundle[n])).hexdigest() for n in SECTIONS}
    h["__content__"] = hashlib.sha256(canonical_bytes(
        {k: v for k, v in bundle.items() if k != "hashes"})).hexdigest()
    bundle["hashes"] = h
    return bundle


def test_verify_separates_integrity_from_server_match(client):
    a = _analyze_csv(client, CSV_A)
    _decide(client, a["analysis_id"])
    b = client.post("/api/export", json={"analysis_id": a["analysis_id"]}).json()
    v = client.post("/api/export/verify", json=b).json()
    assert v["integrity_ok"] and v["server_record"]["status"] == "match"

    # attacker rewrites score AND recomputes all hashes: integrity passes, server match fails
    t = copy.deepcopy(b)
    t["analysis"]["score"] = 2.0
    v = client.post("/api/export/verify", json=_rehash(t)).json()
    assert v["integrity_ok"] and v["server_record"]["status"] == "mismatch"

    # evidence swapped + rehashed
    t = copy.deepcopy(b)
    t["analysis"]["evidence"][0]["text"] = "Subject: someone else"
    v = client.post("/api/export/verify", json=_rehash(t)).json()
    assert v["server_record"]["status"] == "mismatch"

    # decision taken from another analysis + rehashed
    other = _analyze_csv(client, CSV_B)
    _decide(client, other["analysis_id"], decision="dismiss", note="documented legitimate trade")
    ob = client.post("/api/export", json={"analysis_id": other["analysis_id"]}).json()
    t = copy.deepcopy(b)
    t["decision"] = ob["decision"]
    v = client.post("/api/export/verify", json=_rehash(t)).json()
    assert any("decision" in p for p in v["server_record"]["problems"])

    # forged analysis_id
    t = copy.deepcopy(b)
    t["identifiers"]["analysis_id"] = "an-" + "f" * 32
    v = client.post("/api/export/verify", json=_rehash(t)).json()
    assert v["server_record"]["status"] == "not_found"

    # exported_at is covered by the content hash now
    t = copy.deepcopy(b)
    t["exported_at"] = "1999-01-01T00:00:00+00:00"
    assert not client.post("/api/export/verify", json=t).json()["integrity_ok"]


def test_analyst_name_and_justification_are_required(client):
    a = _analyze_csv(client, CSV_A)
    base = {"analysis_id": a["analysis_id"], "decision": "dismiss"}
    assert client.post("/api/decision", json={**base, "note": "long enough reason"}).status_code == 422
    assert client.post("/api/decision", json={**base, "analyst": "AB", "note": "short"}).status_code == 422
    assert client.post("/api/decision", json={**base, "analyst": "  ", "note": "long enough reason"}
                       ).status_code == 422


# ---------------- 4. no silent substitution on import ----------------
@pytest.mark.parametrize("value,fmt,expected", [
    ("43 500 000", "strict", 43_500_000), ("4,5 млн", "strict", 4_500_000),
    ("45000000.50", "strict", 45_000_000.5), ("1 234 567,89", "strict", 1_234_567.89),
    ("1.234.567", "strict", 1_234_567), ("43 500 000 UZS", "strict", 43_500_000),
    ("300.000", "dot-thousands", 300_000), ("4,500", "comma-thousands", 4_500),
    ("4,500.25", "comma-thousands", 4_500.25),
])
def test_supported_amount_formats(value, fmt, expected):
    assert parse_amount_strict(value, fmt) == expected


@pytest.mark.parametrize("value", ["12abc", "4,500", "1.234", "-500", "0", "12 34", "1e6", "", "abc"])
def test_rejected_amounts(value):
    with pytest.raises(AmountFormatError):
        parse_amount_strict(value, "strict")


@pytest.mark.parametrize("row,needle", [
    ("01.05.2026,12abc,in,X,person,p2p,", "amount '12abc'"),
    ("01.05.2026,\"4,500\",in,X,person,p2p,", "ambiguous separator"),
    ("01.05.2026,1000,banana,X,person,p2p,", "direction 'banana'"),
    ("01.05.2026,1000,,X,person,p2p,", "direction is missing"),
    ("01.05.2026,1000,in,X,person,teleport,", "channel 'teleport'"),
    ("01.05.2026,1000,in,,person,p2p,", "counterparty_name is missing"),
    ("01.05.2026,1000,in,X,alien,p2p,", "counterparty_kind 'alien'"),
    ("01.01.2099,1000,in,X,person,p2p,", "after the analysis date"),
    ("31.02.2026,1000,in,X,person,p2p,", "not recognised"),
])
def test_bad_rows_are_rejected_with_row_numbers(row, needle):
    with pytest.raises(InputValidationError) as ei:
        case_from_csv(HDR + row + "\n")
    assert any(e.startswith("row 1") and needle in e for e in ei.value.errors), ei.value.errors


def test_duplicate_ids_and_missing_columns_are_rejected():
    with pytest.raises(InputValidationError) as ei:
        case_from_csv("id,ts,amount,direction,counterparty_name\nT1,01.05.2026,1000,in,X\n"
                      "T1,02.05.2026,2000,in,Y\n")
    assert any("duplicate transaction id 'T1'" in e for e in ei.value.errors)
    with pytest.raises(InputValidationError) as ei:
        case_from_csv("ts,amount,counterparty_name\n01.05.2026,1000,X\n")
    assert "direction" in ei.value.errors[0]


def test_explicit_amount_format_resolves_ambiguity(client):
    r = client.post("/api/analyze", json={"csv_text": HDR + "01.05.2026,\"4,500\",in,X,person,p2p,\n"})
    assert r.status_code == 422 and "ambiguous" in r.json()["detail"]
    res = _analyze_csv(client, HDR + "01.05.2026,\"4,500\",in,X,person,p2p,\n",
                       amount_format="comma-thousands")
    assert res["transactions"][0]["amount"] == 4500


def test_missing_channel_is_recorded_as_unknown_not_p2p():
    case = case_from_csv("ts,amount,direction,counterparty_name\n01.05.2026,1000,in,X\n")
    assert case.transactions[0].channel == "unknown"
    assert any("channel not provided" in n for n in case.input_notes)


def test_missing_subject_metadata_is_not_invented():
    case = case_from_csv(CSV_A)
    assert case.account_age_days is None and case.declared_turnover_monthly is None
    res, _ = analyze(case.model_dump(), llm=DEAD_LLM, want_narrative=False)
    assert "account age NOT PROVIDED" in res.evidence[0].text
    assert "400" not in res.evidence[0].text
    assert set(res.input_summary["imputed"]) == {"account_age_days", "declared_turnover_monthly"}
    assert res.decision_hint.startswith("PROVISIONAL")
    sc03 = next(s for s in res.scenarios if s.code == "SC-03")
    assert sc03.detail.startswith("NOT EVALUATED")


# ---------------- 5. numeric checks of the note ----------------
EV = [EvidenceItem(id="E1", kind="feature", text="total_in = 210.0 mln UZS (score impact +12.0 pp)"),
      EvidenceItem(id="E2", kind="transaction", text="tx T1 2026-03-02T10:00:00 in 48.9 mln UZS from A via p2p"),
      EvidenceItem(id="E3", kind="aggregate", text="Case window: 12 transactions (10 in, 2 out)")]


@pytest.mark.parametrize("note,bucket", [
    ("Subject received 987.6 mln UZS [E1].", "unsupported_numbers"),
    ("Subject received 750 mln UZS [E1].", "unsupported_numbers"),
    ("There were 37 transactions [E3].", "unsupported_numbers"),
    ("Payment on 2026-03-09 [E2].", "unsupported_numbers"),
    ("Inflow 48.9 mln UZS [E1].", "miscited_numbers"),
    ("Inflow 48.9 mln UZS without any citation.", "uncited_numbers"),
])
def test_fabricated_or_miscited_numbers_are_flagged(note, bucket):
    c = verify_narrative(note, EV)
    assert getattr(c, bucket) and c.status == "issues"


@pytest.mark.parametrize("note", [
    "Inflow 210.0 mln UZS [E1]; one inflow of 48.9 mln on 2026-03-02 [E2].",
    "One inflow of 49 mln UZS [E2].",  # rounding of the evidence value
    "One inflow of 48 900 000 UZS [E2].",  # full UZS form of the same value
    "There were 12 transactions, 10 in and 2 out [E3].",
])
def test_supported_numbers_pass(note):
    c = verify_narrative(note, EV)
    assert c.status == "consistent", c


def test_meaning_is_not_verified_and_says_so():
    c = verify_narrative("Subject SENT 210.0 mln UZS out of the account [E1].", EV)
    assert c.status == "consistent" and c.semantics == "not_verified"


def test_template_note_is_consistent_for_every_demo_case():
    for line in (ROOT / "data/generated/cases_demo.jsonl").read_text().splitlines():
        res, _ = analyze(json.loads(line), llm=DEAD_LLM, want_narrative=False)
        assert res.narrative_check.status == "consistent", (res.case_id, res.narrative_check)


# ---------------- 6. truncated LLM output ----------------
class _FakeLLM(LLMClient):
    def __init__(self, text: str, finish: str):
        super().__init__(base_url="http://fake/v1", model="fake")
        self._text, self._finish = text, finish

    def chat(self, system, user, max_tokens=480, temperature=0.15):
        self.last_stats = LLMStats(base_url=self.base_url, model=self.model, available=True,
                                   finish_reason=self._finish, completion_tokens=480)
        return self._text


def test_truncated_llm_draft_is_marked_incomplete():
    raw = json.loads((ROOT / "data/generated/cases_demo.jsonl").read_text().splitlines()[0])
    res, events = analyze(raw, llm=_FakeLLM("**SUMMARY**\nInflow of 579.0 mln UZS on 2026-05", "length"))
    assert res.llm_draft["status"] == "truncated"
    assert res.llm_draft["check"]["complete"] is False
    assert res.llm_draft["check"]["status"] == "issues"
    assert any("INCOMPLETE" in str(e.get("detail")) for e in events)
    assert res.narrative.startswith("**1) SUMMARY** (template")  # primary note unaffected
    ok, _ = analyze(raw, llm=_FakeLLM("Inflow 579.0 mln UZS [E9].", "stop"))
    assert ok.llm_draft["status"] == "complete"


def test_store_rejects_malformed_ids(tmp_path):
    assert store.load(tmp_path, "../x") is None
    assert store.load(tmp_path, "an-" + "0" * 32) is None


def _js_roundtrip(obj):
    """What JSON.parse + JSON.stringify in the browser does to numbers: 80.0 -> 80."""
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _js_roundtrip(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_js_roundtrip(v) for v in obj]
    return obj


def test_package_saved_by_the_browser_still_verifies(client):
    a = _analyze_csv(client, CSV_A)
    _decide(client, a["analysis_id"])
    b = client.post("/api/export", json={"analysis_id": a["analysis_id"]}).json()
    v = client.post("/api/export/verify", json=_js_roundtrip(b)).json()
    assert v["integrity_ok"], v["problems"]
    assert v["server_record"]["status"] == "match", v["server_record"]
