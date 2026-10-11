"""Deterministic checks of an investigation note against its evidence pack.

Three separate questions, reported separately (never folded into one score):

1. Citation IDs — does every [E#] point at an evidence item we supplied?
2. Numeric/date consistency — does every number, amount (with scale words such
   as "mln") and ISO date in a sentence match a value in the evidence items
   cited IN THAT SENTENCE, up to the rounding the sentence itself uses?
   Values found only in other evidence items are "miscited"; values in a
   sentence without any citation are "uncited"; values found nowhere are
   "unsupported".
3. Meaning — NOT machine-verified. A valid citation and matching numbers do
   not make a claim true (e.g. "inflow" vs "outflow", "SC-01 supported").

These are warnings for the analyst; they do not block any action.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schemas import EvidenceItem, NarrativeCheck

CITATION_RE = re.compile(r"\[(E\d{1,3})\]")
_DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2})?)?(?!\d)")
_TIME_RE = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)")
_HEADING_RE = re.compile(r"^\s*[*#\s]*\d\)", re.MULTILINE)
# number forms: 1,234,567.8 | 48 900 000 | 48.9 | 4,5 ; ids (SC-01, row-4,
# T0036, E5, snake_case_2) are excluded by the look-behind
_NUM_RE = re.compile(
    r"(?<![A-Za-z0-9_\-#/Ѐ-ӿ])"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?:\s*(mln|million|млн|bn|billion|mlrd|млрд|thousand|тыс))?",
    re.IGNORECASE,
)
_SCALES = {"mln": 1e6, "million": 1e6, "млн": 1e6, "bn": 1e9, "billion": 1e9, "mlrd": 1e9,
           "млрд": 1e9, "thousand": 1e3, "тыс": 1e3}
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZЀ-ӿ*\-•])|\n+")


@dataclass(frozen=True)
class _Num:
    text: str
    value: float
    tol: float  # half a unit of the precision the text itself uses


def _numbers(text: str) -> list[_Num]:
    out: list[_Num] = []
    for m in _NUM_RE.finditer(text):
        raw, scale_word = m.group(1), m.group(2)
        s = raw.replace(" ", " ")
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
            s = s.replace(",", "")
        else:
            s = s.replace(" ", "").replace(",", ".")
        try:
            v = float(s)
        except ValueError:
            continue
        decimals = len(s.split(".")[1]) if "." in s else 0
        scale = _SCALES.get((scale_word or "").lower(), 1.0)
        if scale == 1.0 and decimals == 0 and 1900 <= v <= 2099 and len(s) == 4:
            continue  # bare year — handled as part of dates, not as an amount
        out.append(_Num(m.group(0).strip(), v * scale, 0.5 * 10 ** -decimals * scale + 1e-9))
    return out


def _strip_non_claims(text: str) -> str:
    text = CITATION_RE.sub(" ", text)
    text = _DATE_RE.sub(" ", text)
    text = _TIME_RE.sub(" ", text)
    return _HEADING_RE.sub(" ", text)


def _evidence_index(evidence: list[EvidenceItem]) -> dict[str, tuple[list[float], set[str]]]:
    idx: dict[str, tuple[list[float], set[str]]] = {}
    for e in evidence:
        dates = set(_DATE_RE.findall(e.text))
        idx[e.id] = ([n.value for n in _numbers(_strip_non_claims(e.text))], dates)
    return idx


def _matches(n: _Num, values: list[float]) -> bool:
    return any(abs(n.value - v) <= n.tol + 1e-9 * max(abs(v), 1.0) for v in values)


def _sentences(text: str) -> list[str]:
    return [s for s in _SENT_SPLIT.split(text) if s and s.strip()]


def verify_narrative(narrative: str, evidence: list[EvidenceItem],
                     complete: bool = True) -> NarrativeCheck:
    allowed = {e.id for e in evidence}
    cited = CITATION_RE.findall(narrative)
    invalid = [c for c in cited if c not in allowed]
    idx = _evidence_index(evidence)
    all_values = [v for vals, _ in idx.values() for v in vals]
    all_dates = {d for _, ds in idx.values() for d in ds}

    unsupported: list[str] = []
    miscited: list[str] = []
    uncited: list[str] = []
    checked = supported = 0
    for sent in _sentences(narrative):
        sent_cites = [c for c in CITATION_RE.findall(sent) if c in idx]
        own_vals = [v for c in sent_cites for v in idx[c][0]]
        own_dates = {d for c in sent_cites for d in idx[c][1]}
        claims: list[tuple[str, bool, bool]] = []  # (text, in cited ev, anywhere)
        for d in _DATE_RE.findall(sent):
            claims.append((d, d in own_dates, d in all_dates))
        for n in _numbers(_strip_non_claims(sent)):
            claims.append((n.text, _matches(n, own_vals), _matches(n, all_values)))
        for text, own, anywhere in claims:
            checked += 1
            if own:
                supported += 1
            elif not anywhere:
                unsupported.append(text)
            elif sent_cites:
                miscited.append(text)
            else:
                uncited.append(text)

    n_cites = len(cited)
    # share of [E#] ids that exist; zero citations is reported as 0.0 (not 'N/A')
    id_share = 0.0 if n_cites == 0 else (n_cites - len(invalid)) / n_cites
    consistent = (n_cites > 0 and not invalid and not unsupported and not miscited
                  and not uncited and complete)
    return NarrativeCheck(
        citation_precision=round(id_share, 3),
        checked_citations=n_cites,
        invalid_citations=invalid,
        unverified_numbers=(unsupported + miscited + uncited)[:12],
        numbers_checked=checked,
        numbers_supported=supported,
        unsupported_numbers=unsupported[:12],
        miscited_numbers=miscited[:12],
        uncited_numbers=uncited[:12],
        numeric_consistency=round(supported / checked, 3) if checked else None,
        complete=complete,
        status="consistent" if consistent else "issues",
        mode="llm",
    )
