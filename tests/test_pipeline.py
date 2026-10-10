"""Scenario rules, entity resolution, verifier, pipeline and API tests."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.features import build_entity_clusters, extract_features  # noqa: E402
from app.core.ingest import case_from_csv, normalize_case  # noqa: E402
from app.core.pipeline import analyze, rule_component  # noqa: E402
from app.core.scenarios import run_scenarios  # noqa: E402
from app.core.schemas import CaseRecord, EvidenceItem, Transaction  # noqa: E402
from app.core.verifier import verify_narrative  # noqa: E402

T0 = datetime(2026, 5, 1, 10, 0, 0)


def _tx(i, amount, direction, name, kind="person", channel="p2p", memo="", days=0, phone=""):
    frm, to = ("SUBJ", "subject") if direction == "in" else (name, kind)
    frm_acct, to_acct = ("SUBJ", f"cp{i}") if direction == "in" else (f"cp{i}", "SUBJ")
    if direction == "in":
        frm, to = name, "SUBJ"
        frm_acct, to_acct = f"cp{i}", "SUBJ"
        from_kind = kind
        to_kind = "subject"
    else:
        frm, to = "SUBJ", name
        frm_acct, to_acct = "SUBJ", f"cp{i}"
        from_kind = "subject"
        to_kind = kind
    return Transaction(
        id=f"T{i:03d}", ts=(T0 + timedelta(days=days)).isoformat(), amount=amount,
        direction=direction, from_account=frm_acct, from_name=frm, from_kind=from_kind,  # type: ignore[arg-type]
        to_account=to_acct, to_name=to, to_kind=to_kind,  # type: ignore[arg-type]
        channel=channel, memo=memo, phone=phone,  # type: ignore[arg-type]
    )


def make_case(txs, **kw) -> CaseRecord:
    base = dict(
        case_id="TEST-1", subject_account="SUBJ", subject_name="Test Subject",
        account_age_days=400, declared_turnover_monthly=20_000_000, branch="Tashkent",
        transactions=txs,
    )
    base.update(kw)
    return CaseRecord(**base)  # type: ignore[arg-type]


# ---------------- scenarios ----------------
def test_structuring_rule_hits():
    txs = [
        _tx(i, 43_000_000 + i * 100_000, "in", f"Sender {i}", days=i * 3)
        for i in range(6)
    ]
    hits = run_scenarios(make_case(txs))
    sc01 = next(h for h in hits if h.code == "SC-01")
    assert sc01.matched and sc01.evidence
    assert rule_component(hits) > 0


def test_structuring_rule_misses_far_below_threshold():
    txs = [_tx(i, 30_000_000, "in", f"S{i}", days=i * 3) for i in range(6)]
    hits = run_scenarios(make_case(txs))
    assert not next(h for h in hits if h.code == "SC-01").matched


def test_rapid_pass_through_hits():
    txs = []
    for i in range(4):
        txs.append(_tx(2 * i, 100_000_000, "in", f"In{i}", days=i))
        txs.append(_tx(2 * i + 1, 95_000_000, "out", f"Out{i}", days=i))
    txs[1] = txs[1].model_copy(update={"ts": (T0 + timedelta(days=0, hours=3)).isoformat()})
    hits = run_scenarios(make_case(txs))
    assert next(h for h in hits if h.code == "SC-02").matched


def test_mule_rule_requires_young_account():
    txs = [_tx(i, 10_000_000, "in", f"Person {i}", days=i) for i in range(10)]
    young = run_scenarios(make_case(txs, account_age_days=30))
    old = run_scenarios(make_case(txs, account_age_days=500))
    assert next(h for h in young if h.code == "SC-03").matched
    assert not next(h for h in old if h.code == "SC-03").matched


def test_turnover_mismatch_rule():
    txs = [_tx(i, 300_000_000, "in", f"Biz {i}", kind="business", days=i * 5) for i in range(6)]
    hits = run_scenarios(make_case(txs, declared_turnover_monthly=20_000_000))
    assert next(h for h in hits if h.code == "SC-06").matched


# ---------------- entity resolution ----------------
def test_entity_cluster_merges_transliteration_variants():
    txs = [
        _tx(0, 1_000_000, "in", "Temur Karimov"),
        _tx(1, 1_000_000, "in", "Темур Каримов"),
        _tx(2, 1_000_000, "in", "T. Karimov"),
        _tx(3, 1_000_000, "in", "Someone Else"),
    ]
    case = make_case(txs)
    clusters = build_entity_clusters(case)
    assert clusters["cp0"] == clusters["cp1"] == clusters["cp2"]
    assert clusters["cp3"] != clusters["cp0"]
    feats = extract_features(case)
    assert feats["uniq_in"] == 2  # three spellings collapsed + one other


# ---------------- verifier ----------------
def _ev():
    return [
        EvidenceItem(id="E1", kind="feature", text="total_in = 935.0 mln UZS"),
        EvidenceItem(id="E2", kind="transaction", text="tx T001 2026-05-01 in 43.0 mln UZS", ref="T001"),
    ]


def test_verifier_accepts_valid_citations():
    note = "Inflow was 935.0 mln UZS [E1], see also [E2]."
    check = verify_narrative(note, _ev())
    assert check.citation_precision == 1.0
    assert not check.invalid_citations
    assert not check.unverified_numbers


def test_verifier_flags_unknown_citation_and_invented_number():
    note = "Total flow 1 234 567 000 UZS [E9] based on [E1]."
    check = verify_narrative(note, _ev())
    assert "E9" in check.invalid_citations
    assert any("1234567000" in n.replace(" ", "") or "1" in n for n in check.unverified_numbers) or check.unverified_numbers


def test_verifier_zero_citations_is_zero_precision():
    check = verify_narrative("No citations at all, numbers 555 000 000 here.", _ev())
    assert check.checked_citations == 0
    assert check.citation_precision == 0.0


# ---------------- ingest ----------------
def test_case_from_csv_messy_jury_input():
    csv_text = (
        "Дата,Сумма,type,counterparty,memo\n"
        '05.04.2026 10:12,"43 500 000",in,Abdurahmon Karimov,\n'
        "12.04.2026 11:40,47800000,in,Dilnoza Yusupova,qarz\n"
        "19.04.2026 09:55,44100000,out,Savdo Markaz MChJ,tovar\n"
    )
    case = case_from_csv(csv_text)
    assert len(case.transactions) == 3
    assert case.transactions[0].amount == 43_500_000
    assert case.transactions[0].ts.startswith("2026-04-05")
    assert case.transactions[2].direction == "out"
    # chronological order preserved
    assert case.transactions[0].ts < case.transactions[1].ts < case.transactions[2].ts


# ---------------- pipeline ----------------
def test_pipeline_end_to_end_on_generated_case():
    path = ROOT / "data/generated/cases_demo.jsonl"
    if not path.exists():
        pytest.skip("generated demo data not present")
    raw = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    res, events = analyze(raw, want_narrative=False)
    assert 0 <= res.score <= 100
    assert res.risk_band in {"low", "medium", "high", "critical"}
    assert len(res.scenarios) == 6
    assert res.evidence and res.evidence[0].id == "E1"
    assert len(res.transactions) == len(raw["transactions"])
    assert [e["stage"] for e in events] == [t.stage for t in res.timings]
    assert res.narrative_check.citation_precision >= 0
    # deterministic fallback is labelled honestly
    assert res.narrative_check.mode == "deterministic"


def test_pipeline_normalizes_messy_amounts_in_generated_data():
    path = ROOT / "data/generated/cases_test.jsonl"
    if not path.exists():
        pytest.skip("generated test data not present")
    raw = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    case = normalize_case(raw)
    assert all(isinstance(t.amount, float) and t.amount > 0 for t in case.transactions)
    assert all(t.ts for t in case.transactions)


# ---------------- API ----------------
def test_api_endpoints():
    from app.api import routes
    from app.core.llm import LLMClient
    from fastapi.testclient import TestClient

    # keep the test hermetic: force the deterministic narrative path
    routes._llm = LLMClient(base_url="http://127.0.0.1:1/v1", model="none")

    from app.main import app

    with TestClient(app) as client:
        h = client.get("/api/health").json()
        assert h["status"] == "ok"
        assert "model_version" in h

        q = client.get("/api/queue").json()
        assert q["total"] > 0 and "score" in q["cases"][0]
        # ground truth labels must NOT leak through the queue API
        assert "labels" not in q["cases"][0]

        cases = client.get("/api/cases").json()["cases"]
        assert cases

        csv_text = "ts,amount,direction,counterparty_name\n01.05.2026,1000000,in,Test Person\n"
        r = client.post("/api/analyze", json={"csv_text": csv_text})
        assert r.status_code == 200
        body = r.text
        assert "event: stage" in body and "event: result" in body
        # bad payload -> 4xx, not a crash
        assert client.post("/api/analyze", json={}).status_code == 422
