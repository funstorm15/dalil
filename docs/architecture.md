# DALIL — architecture notes

See the README §3 for the diagram. This file records decisions a reviewer may probe.

## Why a rules + ML ensemble, not ML-only?

Regulators and auditors must be able to *see* why a case was escalated. The scenario layer
(SC-01..SC-06) is deterministic, explainable code; the model adds recall on subtler variants.
Score = 0.7 · calibrated ML probability + 0.3 · normalised rule severity, mapped to bands
25/50/75. Escalation band ≥ 50. The mixture weight was chosen so a hard rule hit alone can
never escalate a case the model strongly rejects (min ML contribution ≈ 21 pts at cap).

## Why local LLM + OpenAI-compatible API?

Bank perimeter: transaction data cannot leave. llama.cpp exposes `/v1/chat/completions`,
the same contract as on-prem vLLM/TGI, so swapping the runtime in production is an env var
(`LLM_BASE_URL`), not a code change. No external key exists in this repo.

## Why verify citations in code?

An LLM that invents an amount is a regulatory liability. `verifier.py` re-extracts every
`[E#]` reference and every number ≥ 1 000 from the note and checks it against the evidence
pack. Failures surface in the UI (red chips) and in the audit log; the analyst is never shown
an unchecked note.

## Failure modes & mitigations

| Failure | Behaviour |
|---|---|
| LLM down / timeout (90 s) | Deterministic extractive narrative, labelled "deterministic extract — LLM offline" |
| LLM invents citation | Verifier flags chip + audit entry; note still shown but visually marked |
| Malformed CSV | 422 with per-row parse errors; queue cases are pre-validated |
| Model file missing | Pipeline serves rules-only score, health endpoint reports `model_version: rules-only` |
| Cold start on Space | `/api/health` 200 only after warm-up; HF healthcheck start-period 120 s |

## Security notes

- No secrets in repo; Space token lives in GitHub Actions secrets only.
- API has no auth (demo tier). Production note: sit behind the bank SSO reverse proxy;
  audit JSONL is append-only on a volume.
