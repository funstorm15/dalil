"""REST + SSE API."""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import config
from ..core import audit as audit_log
from ..core import store
from ..core.llm import LLMClient
from ..core.pipeline import analyze
from ..core.schemas import AnalyzeRequest, DecisionIn

router = APIRouter(prefix="/api")

_queue_cache: list[dict] | None = None
_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient(base_url=config.LLM_BASE_URL, model=config.LLM_MODEL)
    return _llm


def _load_cases_file(name: str) -> list[dict]:
    path = config.GENERATED_DIR / name
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_queue() -> list[dict]:
    global _queue_cache
    if _queue_cache is not None:
        return _queue_cache
    if config.QUEUE_PATH.exists():
        _queue_cache = json.loads(config.QUEUE_PATH.read_text(encoding="utf-8"))
        return _queue_cache
    # fallback: unscored queue from demo cases
    rows = _load_cases_file("cases_demo.jsonl")
    _queue_cache = [
        {"case_id": r["case_id"], "subject_name": r["subject_name"],
         "n_tx": len(r["transactions"]), "score": None, "risk_band": None,
         "labels": r["labels"], "opened_at": r.get("opened_at", "")}
        for r in rows
    ]
    return _queue_cache


@router.get("/health")
def health() -> dict:
    st = get_llm().health()
    return {
        "status": "ok",
        "model_version": _model_version(),
        "llm": st.__dict__,
        "queue_size": len(load_queue()),
        "audit_entries": len(audit_log.tail(200, path=config.AUDIT_PATH)),
    }


def _model_version() -> str:
    from ..core.riskmodel import load_bundle
    return str(load_bundle().get("version", "unknown"))


@router.get("/queue")
def queue(limit: int = 80) -> dict:
    """Alert queue for the UI — ground-truth labels are intentionally stripped."""
    out = [
        {k: row.get(k) for k in
         ("case_id", "subject_name", "subject_kind", "branch", "opened_at",
          "n_tx", "score", "risk_band", "scenarios")}
        for row in load_queue()[:limit]
    ]
    return {"cases": out, "total": len(load_queue())}


@router.get("/cases")
def cases(limit: int = 80) -> dict:
    """Case picker for the investigator view (no pre-judgement shown)."""
    rows = _load_cases_file("cases_demo.jsonl")
    out = [
        {"case_id": r["case_id"], "subject_name": r["subject_name"],
         "subject_kind": r["subject_kind"], "n_tx": len(r["transactions"]),
         "opened_at": r.get("opened_at", ""), "branch": r.get("branch", "")}
        for r in rows[:limit]
    ]
    return {"cases": out}


@router.get("/cases/{case_id}")
def get_case(case_id: str) -> dict:
    for r in _load_cases_file("cases_demo.jsonl"):
        if r["case_id"] == case_id:
            return r
    raise HTTPException(404, "case not found")


def _demo_case(case_id: str) -> dict | None:
    return next((r for r in _load_cases_file("cases_demo.jsonl") if r["case_id"] == case_id), None)


@router.post("/analyze")
async def analyze_endpoint(req: AnalyzeRequest, request: Request) -> StreamingResponse:
    """Analyse a demo case or a CSV. Every run gets a new analysis_id; the server
    stores the exact input, its SHA-256 and the computed result."""
    from ..core.ingest import InputValidationError, case_from_csv

    if req.case_id:
        raw = _demo_case(req.case_id)
        if raw is None:
            raise HTTPException(404, "case not found")
        inp = store.input_record("synthetic_case", raw)
    elif req.csv_text:
        if len(req.csv_text.encode()) > config.MAX_CSV_BYTES:
            raise HTTPException(413, "CSV too large")
        inp = store.input_record("csv_input", req.csv_text, req.amount_format)
        case_id = f"CSV-{store.sha256_json(inp)[:12]}"
        try:
            case = case_from_csv(req.csv_text, case_id=case_id, amount_format=req.amount_format)
        except InputValidationError as e:
            more = f" (+{len(e.errors) - 8} more)" if len(e.errors) > 8 else ""
            raise HTTPException(422, "Input rejected — " + "; ".join(e.errors[:8]) + more) from e
        except Exception as e:  # noqa: BLE001 — malformed CSV structure
            raise HTTPException(422, f"Input rejected — CSV could not be read: {e}") from e
        raw = case.model_dump()
    else:
        raise HTTPException(422, "case_id or csv_text required")
    input_sha = store.sha256_json(inp)
    analysis_id = store.new_analysis_id()
    llm = get_llm()

    def gen():
        import queue as _q
        import threading

        from ..core.ingest import InputValidationError

        ev_q: _q.Queue = _q.Queue()
        box: dict = {}

        def run() -> None:
            t0 = time.perf_counter()
            try:
                result, _events = analyze(raw, llm=llm, want_narrative=req.llm_draft,
                                          emit=lambda ev: ev_q.put(dict(ev)))
                result.analysis_id = analysis_id
                result.input_sha256 = input_sha
                store.save(config.ANALYSES_DIR, analysis_id, inp, input_sha, result.model_dump())
                box["result"] = result
            except InputValidationError as e:
                box["error"] = "Input rejected — " + "; ".join(e.errors[:8])
            except Exception as e:  # noqa: BLE001 — never kill the stream silently
                box["error"] = str(e)[:300]
            finally:
                box["wall_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                ev_q.put(None)

        th = threading.Thread(target=run, daemon=True)
        th.start()
        while True:
            try:
                ev = ev_q.get(timeout=1.0)
            except _q.Empty:
                continue
            if ev is None:
                break
            yield f"event: stage\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
        if "error" in box:
            yield f"event: error\ndata: {json.dumps({'error': box['error']}, ensure_ascii=False)}\n\n"
            return
        yield f"event: result\ndata: {json.dumps(box['result'].model_dump(), ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {json.dumps({'wall_ms': box['wall_ms']})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _record_or_404(analysis_id: str) -> dict:
    rec = store.load(config.ANALYSES_DIR, analysis_id)
    if rec is None:
        raise HTTPException(404, "unknown analysis_id — run the analysis on this server first")
    return rec


@router.get("/analysis/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    """Stored server result + decisions for one analysis run (used after a page reload)."""
    rec = _record_or_404(analysis_id)
    return {"result": rec["result"], "input_sha256": rec["input_sha256"],
            "result_sha256": rec["result_sha256"], "created_at": rec["created_at"],
            "decisions": audit_log.for_analysis(analysis_id, path=config.AUDIT_PATH)}


@router.post("/decision")
def decision(dec: DecisionIn) -> dict:
    """Record an analyst decision on a stored analysis. Score, note checks and
    model version come from the server record, never from the client."""
    rec = _record_or_404(dec.analysis_id)
    analyst, note = dec.analyst.strip(), dec.note.strip()
    if len(analyst) < 2:
        raise HTTPException(422, "analyst name is required (self-declared, not authenticated)")
    if len(note) < 10:
        raise HTTPException(422, "a justification of at least 10 characters is required")
    res = rec["result"]
    entry = audit_log.record_decision(
        case_id=res["case_id"], score=float(res["score"]), decision=dec.decision,
        analyst=analyst, note=note, narrative_check=res.get("narrative_check", {}),
        model_version=res.get("model_version", ""), path=config.AUDIT_PATH,
        analysis_id=rec["analysis_id"], input_sha256=rec["input_sha256"],
        result_sha256=rec["result_sha256"],
    )
    return {"ok": True, "entry": entry.model_dump()}


@router.post("/export")
def export_bundle(payload: dict) -> dict:
    """Export package built from the SERVER record of one analysis_id. Any
    'result' sent by the client is ignored."""
    from ..core.export import build_export
    from ..core.scenarios import RULESET_VERSION

    rec = _record_or_404(str(payload.get("analysis_id") or ""))
    decisions = audit_log.for_analysis(rec["analysis_id"], path=config.AUDIT_PATH)
    return build_export(input_payload=rec["input"], result=rec["result"],
                        decision=decisions[-1] if decisions else None,
                        ruleset_version=RULESET_VERSION, analysis_id=rec["analysis_id"],
                        input_sha256=rec["input_sha256"], result_sha256=rec["result_sha256"])


@router.post("/export/verify")
def export_verify(bundle: dict) -> dict:
    """Two separate checks: (1) integrity — stored hashes vs content; (2) match —
    package vs this server's record for its analysis_id."""
    from ..core.export import compare_with_record, verify_bundle
    from ..core.scenarios import RULESET_VERSION

    integrity = verify_bundle(bundle)
    aid = ((bundle.get("identifiers") or {}).get("analysis_id") if isinstance(bundle, dict) else None) or ""
    rec = store.load(config.ANALYSES_DIR, aid) if aid else None
    server = (compare_with_record(bundle, rec, audit_log.for_analysis(aid, path=config.AUDIT_PATH),
                                  RULESET_VERSION)
              if aid else {"status": "no_analysis_id", "problems": ["package has no analysis_id"]})
    return {**integrity, "integrity_ok": integrity["ok"], "server_record": server}


@router.get("/audit")
def audit(limit: int = 50) -> dict:
    return {"entries": audit_log.tail(limit, path=config.AUDIT_PATH)}


@router.get("/metrics")
def metrics() -> dict:
    out: dict = {}
    for name in ("train_report.json", "eval_report.json"):
        p = config.RESULTS_DIR / name
        if p.exists():
            out[name.replace(".json", "")] = json.loads(p.read_text(encoding="utf-8"))
    return out


@router.get("/system")
def system() -> dict:
    p = config.RESULTS_DIR / "system_facts.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


@router.post("/llm/reconnect")
def llm_reconnect() -> dict:
    return get_llm().health().__dict__
