# DALIL — architecture notes

See the README §3 for the diagram. This file records decisions a reviewer may probe.

## Why a rules + ML ensemble, not ML-only?

Reviewers must be able to *see* why a case was escalated. The scenario layer (SC-01..SC-06)
is deterministic, explainable code; the model adds recall on subtler variants. Score =
0.7 · calibrated ML probability + 0.3 · normalised rule severity, mapped to bands 25/50/75.
Escalation band ≥ 50. A hard rule hit alone cannot escalate a case the model strongly rejects.

## Input validation (no silent substitution)

`core/ingest.py` + `normalize.parse_amount_strict`. Bad rows are rejected with row numbers
(HTTP 422); nothing is coerced to 0, "out", "p2p" or a default account age.

- Amount formats: `strict` (default for CSV; a single `.`/`,` followed by exactly three
  digits such as `4,500` is ambiguous and rejected), `dot-thousands` (`1.234.567,89`),
  `comma-thousands` (`1,234,567.89`); scale words `млн/mln/тыс/k`; currency suffix allowed.
  The synthetic casebook is read with the generator's documented `dot-thousands` convention.
- Required columns: `ts, amount, direction, counterparty_name` (or `from_name` + `to_name`).
- Dates: ISO, `dd.mm.yyyy`, `dd/mm/yyyy`; a date after the analysis day (Asia/Tashkent) is
  rejected; transactions after a case's `opened_at` are kept and reported in warnings.
- Categories: direction in/out (credit/debit, приход/расход); channel one of
  p2p/cash_in/cash_out/atm/card/pos/merchant/wire — empty → `unknown` (+ warning), any other
  text → error; counterparty kind person/business — empty → person (+ warning).
- Subject metadata (account age, declared turnover) is never invented. If missing, SC-03 /
  SC-06 are reported "NOT EVALUATED", the model input is imputed with the training median,
  this is printed in the evidence and warnings, and the recommendation is marked PROVISIONAL.

## The note: template first, LLM draft experimental

The primary investigation note is a template assembled only from evidence text, so every
number in it is copied from the evidence it cites. A local open-weight LLM (llama.cpp,
OpenAI-compatible route, no external key) can add an **experimental draft**. A small model
can mis-state direction, typology or which evidence supports a claim; that is why the draft
is never the record. `finish_reason == "length"` marks a draft INCOMPLETE.

## What the note checks do (and do not do)

`core/verifier.py`, reported as separate statuses:

1. citation IDs — every `[E#]` exists in the evidence list;
2. numbers & dates — every number, amount (incl. "mln" scale) and ISO date in a sentence must
   match a value in the evidence items cited **in that sentence**, within the rounding the
   sentence uses; otherwise it is listed as unsupported / miscited / uncited;
3. completeness — the LLM did not stop at the token limit;
4. meaning — **not** machine-verified. A valid citation and matching numbers do not make a
   claim true.

The checks are warnings shown to the analyst; they do not block decisions or exports.

## Server-side record, decisions and export

Every `/api/analyze` run gets an `analysis_id`; the server stores the exact input, its SHA-256
and the computed result (`core/store.py`, `data/analyses/`). Decisions (`/api/decision`) and
exports (`/api/export`) take only an `analysis_id`: score, evidence and note checks come from
the stored record, never from the browser. Each decision line in `data/audit/audit.log`
carries analysis_id, input hash and result hash.

Export verification has two separate answers:
- integrity — recomputed SHA-256 over canonical JSON equals the stored hashes;
- server match — the package's sections equal this server's stored record and decision log.

Limits: SHA-256 without a trusted signature does not stop someone who controls the whole
package from rewriting content and hashes together (integrity then passes; only the server
match can catch it while the server record exists). The decision log is an ordinary file in
append mode — not tamper-proof, not an immutable audit trail. The analyst name is typed by
the user and is not an authenticated identity.

## Failure modes

| Failure | Behaviour |
|---|---|
| LLM down / timeout (90 s) | template note only; UI: "LLM offline — no draft" |
| LLM draft cut at token limit | draft marked INCOMPLETE, check status "issues" |
| LLM invents a number / cites wrong evidence | listed under the draft as unsupported / miscited |
| Malformed or ambiguous CSV | 422 with per-row messages |
| Unknown analysis_id on decision/export | 404 |

## Security notes

- No secrets in the repo; an optional Space deploy token lives in GitHub Actions secrets only.
- The API has no authentication (demo tier) and binds to 127.0.0.1 in `scripts/run_demo.sh`;
  the public demo is reachable through an ngrok tunnel. A bank deployment would need its own
  authentication, network controls, storage and egress review.
