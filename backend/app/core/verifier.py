"""Deterministic verification of the LLM narrative.

Audit requirement: every citation in the note must point at evidence we
actually supplied, and every number in the note must exist in that evidence.
Violating sentences are flagged for the analyst — the model can be wrong, the
system cannot silently pass it through.
"""
from __future__ import annotations

import re

from .schemas import EvidenceItem, NarrativeCheck

CITATION_RE = re.compile(r"\[(E\d{1,3})\]")
NUMBER_RE = re.compile(r"\d[\d\u00a0 ]*")  # spaces/nbsp, never newlines


def _numbers(text: str) -> set[str]:
    out = set()
    for m in NUMBER_RE.findall(text):
        s = m.strip().rstrip(".").replace("\u00a0", "").replace(" ", "")
        s = s.rstrip(",")
        if len(s) >= 2:
            out.add(s)
    return out


def _norm_num(s: str) -> str:
    s = "".join(s.split()).replace("\u00a0", "").replace(",", "")
    return s


def verify_narrative(narrative: str, evidence: list[EvidenceItem]) -> NarrativeCheck:
    allowed = {e.id for e in evidence}
    cited = CITATION_RE.findall(narrative)
    invalid = [c for c in cited if c not in allowed]

    ev_text = " ".join(e.text for e in evidence)
    ev_numbers = {_norm_num(n) for n in _numbers(ev_text)}
    # numbers the narrative asserts
    body = CITATION_RE.sub(" ", narrative)
    narr_numbers = _numbers(body)
    unverified = []
    for n in sorted(narr_numbers):
        nn = _norm_num(n)
        if not nn or nn in ev_numbers:
            continue
        try:
            val = float(nn)
        except ValueError:
            if len(nn) >= 4:
                unverified.append(n)
            continue
        if len(nn) == 4 and nn.isdigit() and 1900 <= int(nn) <= 2099:
            continue  # bare year — not a money claim
        if abs(val) >= 1000 and nn not in ev_numbers:  # money-scale must be sourced
            unverified.append(n)

    checked = len(cited)
    # fail closed: a note without any citation is not "fully verified"
    precision = 0.0 if checked == 0 else (checked - len(invalid)) / checked
    if unverified:
        precision = min(precision, (checked - len(invalid)) / max(checked, 1))
    return NarrativeCheck(
        citation_precision=round(precision, 3),
        checked_citations=checked,
        invalid_citations=invalid,
        unverified_numbers=unverified[:10],
        mode="llm",
    )
