"""Verifiable export: build, canonical hashing, tamper detection, API round trip."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.export import (  # noqa: E402
    HASH_DISCLAIMER,
    SCHEMA_VERSION,
    build_export,
    canonical_bytes,
    verify_bundle,
)
from app.core.llm import LLMClient  # noqa: E402
from app.core.pipeline import analyze  # noqa: E402
from app.core.scenarios import RULESET_VERSION  # noqa: E402

DEAD_LLM = LLMClient(base_url="http://127.0.0.1:1/v1", model="none")

DECISION = {
    "case_id": "FX-2026-0042",
    "decision": "escalate",
    "analyst": "n.karimova",
    "note": "structure + mule: escalating to supervisor",
}


@pytest.fixture(scope="module")
def demo():
    path = ROOT / "data/generated/cases_demo.jsonl"
    if not path.exists():
        pytest.skip("generated demo data not present")
    raw = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    res, events = analyze(raw, llm=DEAD_LLM, want_narrative=True)
    return raw, res.model_dump(), events


def _bundle(raw, result, decision=DECISION):
    return build_export(
        input_payload={"kind": "synthetic_case", "payload": raw},
        result=result, decision=decision, ruleset_version=RULESET_VERSION)


def test_bundle_builds_and_verifies(demo):
    raw, result, _ = demo
    bundle = _bundle(raw, result)
    assert bundle["schema_version"] == SCHEMA_VERSION
    v = verify_bundle(bundle)
    assert v["ok"], v["problems"]
    # every promised part is actually in the package
    assert bundle["input"]["kind"] == "synthetic_case"
    assert bundle["input"]["payload"]["case_id"] == raw["case_id"]
    assert bundle["identifiers"]["ruleset_version"] == RULESET_VERSION
    assert bundle["identifiers"]["model_version"] == result["model_version"]
    assert bundle["identifiers"]["narrative_mode"] == "deterministic"
    assert bundle["narrative"]["text"]
    assert bundle["narrative"]["mode"] == "deterministic"
    assert bundle["decision"] == DECISION
    assert bundle["analysis"]["score"] == result["score"]
    assert bundle["analysis"]["evidence"]
    assert set(bundle["hashes"]) >= {"input", "identifiers", "analysis",
                                     "narrative", "decision", "__content__"}
    # integrity limits are stated inside the package, not just in docs
    limits = bundle["integrity"]["limits"]
    assert "not a digital signature" in limits
    assert limits == HASH_DISCLAIMER


def test_canonical_encoding_is_order_stable():
    a = canonical_bytes({"b": 1, "a": [2, {"d": 4, "c": 3}]})
    b = canonical_bytes({"a": [2, {"c": 3, "d": 4}], "b": 1})
    assert a == b
    # utf-8, not \uXXXX escapes — Cyrillic stays readable
    assert "Темур" in canonical_bytes({"n": "Темур"}).decode("utf-8")


def test_tampering_with_score_is_detected(demo):
    raw, result, _ = demo
    bundle = _bundle(raw, result)
    bad = copy.deepcopy(bundle)
    bad["analysis"]["score"] = 99.9
    v = verify_bundle(bad)
    assert not v["ok"]
    assert any("section 'analysis'" in p and "hash" in p for p in v["problems"])


def test_tampering_with_narrative_is_detected(demo):
    raw, result, _ = demo
    bundle = _bundle(raw, result)
    bad = copy.deepcopy(bundle)
    bad["narrative"]["text"] += " Fraud confirmed beyond doubt."
    v = verify_bundle(bad)
    assert not v["ok"]
    assert any("section 'narrative'" in p for p in v["problems"])


def test_tampering_with_decision_is_detected(demo):
    raw, result, _ = demo
    bundle = _bundle(raw, result)
    bad = copy.deepcopy(bundle)
    bad["decision"]["decision"] = "release_no_escalation"
    v = verify_bundle(bad)
    assert not v["ok"]
    assert any("section 'decision'" in p for p in v["problems"])


def test_tampering_with_evidence_is_detected(demo):
    raw, result, _ = demo
    bundle = _bundle(raw, result)
    bad = copy.deepcopy(bundle)
    bad["analysis"]["evidence"][0]["text"] = "fabricated evidence line"
    v = verify_bundle(bad)
    assert not v["ok"]


def test_schema_and_structure_problems_are_reported():
    v = verify_bundle({"schema_version": "other/9"})
    assert not v["ok"]
    assert any("schema_version" in p for p in v["problems"])
    assert any("hashes" in p for p in v["problems"])

    v2 = verify_bundle([1, 2, 3])
    assert not v2["ok"] and v2["problems"]


def test_verify_never_raises_on_garbage():
    for junk in (None, 42, "x", {}, {"schema_version": SCHEMA_VERSION}):
        v = verify_bundle(junk)
        assert v["ok"] is False
        assert v["problems"]


def test_export_api_round_trip_and_tamper(demo, monkeypatch, tmp_path):
    from app import config
    from app.api import routes
    from app.main import app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(config, "AUDIT_PATH", tmp_path / "audit.log")
    monkeypatch.setattr(config, "ANALYSES_DIR", tmp_path / "analyses")
    routes._llm = DEAD_LLM

    raw, _, _ = demo
    with TestClient(app) as client:
        result = _sse_result(client.post("/api/analyze", json={"case_id": raw["case_id"]}).text)
        aid = result["analysis_id"]
        # analyst decision first, so the export carries it
        r = client.post("/api/decision", json={
            "analysis_id": aid, "decision": "escalate",
            "analyst": "n.karimova", "note": "escalating: turnover mismatch"})
        assert r.status_code == 200 and r.json()["ok"]

        r = client.post("/api/export", json={"analysis_id": aid})
        assert r.status_code == 200
        bundle = r.json()
        assert bundle["decision"]["decision"] == "escalate"
        assert bundle["decision"]["analysis_id"] == aid
        assert bundle["input"]["kind"] == "synthetic_case"

        v = client.post("/api/export/verify", json=bundle).json()
        assert v["ok"], v["problems"]
        assert v["server_record"]["status"] == "match"

        bad = copy.deepcopy(bundle)
        bad["analysis"]["risk_band"] = "low"
        v2 = client.post("/api/export/verify", json=bad).json()
        assert not v2["ok"] and any("analysis" in p for p in v2["problems"])

        # CSV input: the original text travels with the package
        csv_text = (ROOT / "tests/fixtures/valid_case.csv").read_text(encoding="utf-8")
        res2 = _sse_result(client.post("/api/analyze", json={"csv_text": csv_text}).text)
        b2 = client.post("/api/export", json={"analysis_id": res2["analysis_id"]}).json()
        assert b2["input"]["kind"] == "csv_input"
        assert "47500000" in b2["input"]["payload"]
        assert client.post("/api/export/verify", json=b2).json()["ok"]

        # export without a known analysis is a client error, not a crash
        assert client.post("/api/export", json={}).status_code == 404


def _sse_result(text: str) -> dict:
    for block in text.split("\n\n"):
        if block.startswith("event: result"):
            return json.loads(block.split("data: ", 1)[1])
    raise AssertionError(f"no result event in stream: {text[-300:]}")
