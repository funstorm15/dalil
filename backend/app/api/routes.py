"""REST + SSE API."""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import config
from ..core import audit as audit_log
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
        "audit_entries": len(audit_log.tail(200)),
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


@router.post("/analyze")
async def analyze_endpoint(req: AnalyzeRequest, request: Request) -> StreamingResponse:
    raw: dict | None = None
    if req.case_id:
        raw = None
        for r in _load_cases_file("cases_demo.jsonl"):
            if r["case_id"] == req.case_id:
                raw = r
                break
        if raw is None:
            raise HTTPException(404, "case not found")
    elif req.csv_text:
        if len(req.csv_text.encode()) > config.MAX_CSV_BYTES:
            raise HTTPException(413, "CSV too large")
        from ..core.ingest import case_from_csv
        try:
            case = case_from_csv(req.csv_text, case_id="JURY-INPUT")
        except Exception as e:  # noqa: BLE001 — surface parse errors to the analyst
            raise HTTPException(422, f"CSV parse error: {e}") from e
        raw = case.model_dump()
    else:
        raise HTTPException(422, "case_id or csv_text required")

    llm = get_llm()

    def gen():
        import queue as _q
        import threading

        ev_q: _q.Queue = _q.Queue()
        box: dict = {}

        def run() -> None:
            t0 = time.perf_counter()
            try:
                result, _events = analyze(raw, llm=llm, want_narrative=True,
                                          emit=lambda ev: ev_q.put(dict(ev)))
                box["result"] = result
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
            yield f"event: error\ndata: {json.dumps({'error': box['error']})}\n\n"
            return
        yield f"event: result\ndata: {json.dumps(box['result'].model_dump(), ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {json.dumps({'wall_ms': box['wall_ms']})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/decision")
def decision(dec: DecisionIn) -> dict:
    # decisions require a prior score in this session-less prototype
    saved = [r for r in audit_log.tail(500) if r.get("case_id") == dec.case_id]
    score = saved[0]["score"] if saved else None
    if score is None:
        # look up queue score
        for q in load_queue():
            if q["case_id"] == dec.case_id and q.get("score") is not None:
                score = q["score"]
                break
    if score is None:
        score = 0.0
    entry = audit_log.record_decision(
        case_id=dec.case_id, score=float(score), decision=dec.decision,
        analyst=dec.analyst, note=dec.note, narrative_check={},
        model_version=_model_version(), path=config.AUDIT_PATH,
    )
    return {"ok": True, "entry": entry.model_dump()}


@router.post("/decision/full")
def decision_full(payload: dict) -> dict:
    """Decision attached to a full analysis (used by the investigator UI)."""
    dec = DecisionIn.model_validate(payload.get("decision", {}))
    result = payload.get("result") or {}
    entry = audit_log.record_decision(
        case_id=dec.case_id,
        score=float(result.get("score", 0.0)),
        decision=dec.decision,
        analyst=dec.analyst,
        note=dec.note,
        narrative_check=result.get("narrative_check", {}),
        model_version=result.get("model_version", _model_version()),
        path=config.AUDIT_PATH,
    )
    return {"ok": True, "entry": entry.model_dump()}


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
