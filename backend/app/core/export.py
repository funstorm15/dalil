"""Verifiable export bundles for DALIL analyses.

A bundle is built by the server from its OWN stored analysis record
(core/store.py) — never from a result posted by the browser. It captures:
schema version, the exact input analysed (+ its SHA-256), analysis_id, model
and ruleset identifiers, the analysis results, the evidence pack, the template
note and the experimental LLM draft with their check results, and the analyst
decision bound to this analysis_id.

Two different checks exist:
- integrity (verify_bundle): SHA-256 over canonical JSON (sorted keys, compact
  separators, UTF-8) — detects edits *relative to the stored hashes*;
- server match (compare_with_record): the package's sections equal what this
  server stored for that analysis_id and decision log — only possible while
  the server record exists.
Explicit limits, also shown to users:

- NOT a digital signature, NOT identity attestation, NOT an immutable bank
  audit trail. Anyone who controls the whole bundle can rewrite content and
  hashes together.
- Numeric reproducibility is only claimed for pinned model/ruleset versions.
- The LLM narrative is NOT promised to reproduce bit-for-bit.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "dalil.export/2"
HASH_ALGO = "sha256"
SECTIONS = ("input", "identifiers", "analysis", "narrative", "decision")

HASH_DISCLAIMER = (
    "SHA-256 content hashes only: they detect edits made after export when the "
    "original hashes are kept. This is not a digital signature, not identity "
    "attestation and not an immutable audit trail — whoever controls the whole "
    "package can rewrite both content and hashes. LLM narrative text is not "
    "bit-reproducible; numeric results are reproducible only with the pinned "
    "model and ruleset versions recorded in 'identifiers'."
)


def _canon_numbers(obj: Any) -> Any:
    """Integral floats -> int, so 80.0 and 80 hash the same.

    JSON round-trips through JavaScript (the browser download) drop the '.0';
    without this a package saved from the UI would fail verification.
    """
    if isinstance(obj, float):
        return int(obj) if obj.is_integer() else obj
    if isinstance(obj, dict):
        return {k: _canon_numbers(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canon_numbers(v) for v in obj]
    return obj


def canonical_bytes(obj: Any) -> bytes:
    """Canonical JSON encoding used for hashing: sorted keys, compact separators,
    UTF-8, integral floats written as integers (stable across Python and JS)."""
    return json.dumps(_canon_numbers(obj), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(obj: Any) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def build_export(*, input_payload: dict[str, Any], result: dict[str, Any],
                 decision: dict[str, Any] | None, ruleset_version: str,
                 analysis_id: str = "", input_sha256: str = "", result_sha256: str = "",
                 exported_at: str | None = None) -> dict[str, Any]:
    """Assemble a self-contained export bundle with per-section hashes."""
    input_section = {
        "kind": input_payload.get("kind", "unknown"),
        "case_id": result.get("case_id", ""),
        "amount_format": input_payload.get("amount_format"),
        "payload": input_payload.get("payload"),
        "sha256": input_sha256,
    }
    check = result.get("narrative_check") or {}
    draft = result.get("llm_draft")
    identifiers = {
        "analysis_id": analysis_id,
        "input_sha256": input_sha256,
        "result_sha256": result_sha256,
        "model_version": result.get("model_version", "unknown"),
        "ruleset_version": ruleset_version,
        "llm_model": (draft or {}).get("model") if draft and draft.get("status") != "unavailable" else None,
        "narrative_mode": check.get("mode"),
    }
    analysis = {
        "case_id": result.get("case_id"),
        "score": result.get("score"),
        "risk_band": result.get("risk_band"),
        "decision_hint": result.get("decision_hint"),
        "suspicious": result.get("suspicious"),
        "model_version": result.get("model_version"),
        "top_features": result.get("top_features", []),
        "scenarios": result.get("scenarios", []),
        "evidence": result.get("evidence", []),
        "input_summary": result.get("input_summary", {}),
        "transactions": result.get("transactions", []),
        "timings": result.get("timings", []),
        "total_ms": result.get("total_ms"),
    }
    narrative = {
        "text": result.get("narrative", ""),
        "mode": check.get("mode"),
        "check": check,
        "llm_draft": draft,
    }
    decision_section = dict(decision) if decision else None

    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "exported_at": exported_at or datetime.now(UTC).isoformat(),
        "input": input_section,
        "identifiers": identifiers,
        "analysis": analysis,
        "narrative": narrative,
        "decision": decision_section,
        "integrity": {"algorithm": HASH_ALGO, "scope": "canonical_json", "limits": HASH_DISCLAIMER},
    }
    hashes = {name: _sha256(body[name]) for name in SECTIONS}
    hashes["__content__"] = _sha256(body)
    body["hashes"] = hashes
    return body


def compare_with_record(bundle: dict[str, Any], record: dict[str, Any] | None,
                        decisions: list[dict[str, Any]], ruleset_version: str) -> dict[str, Any]:
    """Does the package match what THIS server stored for its analysis_id?"""
    if record is None:
        return {"status": "not_found",
                "problems": ["no server record for this analysis_id (unknown id or another server)"]}
    expected = build_export(input_payload=record["input"], result=record["result"], decision=None,
                            ruleset_version=ruleset_version, analysis_id=record["analysis_id"],
                            input_sha256=record["input_sha256"], result_sha256=record["result_sha256"])
    problems = [f"section '{name}' differs from the server record"
                for name in ("input", "identifiers", "analysis", "narrative")
                if _sha256(bundle.get(name)) != _sha256(expected[name])]
    dec = bundle.get("decision")
    if dec is not None and not any(_sha256(dec) == _sha256(d) for d in decisions):
        problems.append("section 'decision' is not a decision recorded for this analysis_id")
    return {"status": "match" if not problems else "mismatch", "problems": problems}


def verify_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Recompute hashes; report every mismatch. Never raises on bad input."""
    problems: list[str] = []
    if not isinstance(bundle, dict):
        return {"ok": False, "problems": ["bundle is not a JSON object"], "schema_version": None}
    if bundle.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"schema_version {bundle.get('schema_version')!r} != {SCHEMA_VERSION!r}")
    stored = bundle.get("hashes")
    if not isinstance(stored, dict):
        return {"ok": False, "problems": problems + ["hashes section missing"],
                "schema_version": bundle.get("schema_version")}
    for name in SECTIONS:
        if name not in bundle:
            problems.append(f"section '{name}' missing")
            continue
        actual = _sha256(bundle[name])
        if stored.get(name) != actual:
            problems.append(f"section '{name}': stored hash does not match content")
    if "exported_at" in bundle:
        content = {k: v for k, v in bundle.items() if k != "hashes"}
        if stored.get("__content__") != _sha256(content):
            problems.append("section '__content__' (all sections incl. exported_at): "
                            "stored hash does not match content")
    else:
        problems.append("exported_at missing")
    return {"ok": not problems, "problems": problems,
            "schema_version": bundle.get("schema_version")}


def load_and_verify(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        bundle = json.load(f)
    verdict = verify_bundle(bundle)
    verdict["path"] = path
    return verdict
