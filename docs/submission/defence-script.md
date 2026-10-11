# DALIL — 7-minute defence script (FinTech track) + Q&A

Live demo budget: **≈100 s**, minute 1:15 → 2:55. Demo case: **New CSV → "load template"**
(12 synthetic transactions, no subject metadata). Verified on the release build: score
**83.4 / critical**, **SC-01 structuring hit** (10 deposits of 42–50 mln UZS from 10 senders),
SC-03 and SC-06 **NOT EVALUATED** (metadata missing), recommendation **PROVISIONAL**.

Before the slot: `bash scripts/run_demo.sh` (after any reboot) → open
https://cornbread-left-licking.ngrok-free.dev → "Visit Site". Run the template case once to
warm up. Backup: `localhost:8000` (same UI) · backup video `DALIL-demo-backup.mp4` (53 s, silent screen capture of
the same flow on an isolated local instance with the LLM draft on; recorded 11 Oct 07:17).

---

## 0:00–0:30 · Problem

"An AML analyst reviews alerts by scrolling transactions, transliterating UZ/RU names and
matching typologies. On **our own synthetic benchmark**, a rules-only layer flags
**57.0% of clean cases** and misses **20.9%** of the held-out
laundering variants. Alert volumes and minutes per alert in our cost slide are
**assumptions**, not a bank measurement."

## 0:30–1:15 · What DALIL is

"DALIL takes a case CSV or a queue alert and gives one screen: an explainable 0–100 score
(70% calibrated model + 30% typology rules), the rule hits with their transactions, and an
investigation note built **only from the evidence list**. A local open-weight LLM can add an
**experimental draft** — no external AI API is called. Every claim's number is checked against
the evidence it cites; the **meaning** is not machine-checked — that is the analyst's job.
The analyst decides; the server keeps the decision bound to that exact analysis and input
hash, and exports a package it builds from its own record."

## 1:15–2:55 · LIVE DEMO (≈100 s) — cues

| t | screen | say |
|---|---|---|
| 0–10 s | Investigate → **New CSV** → **load template** → (LLM draft box **unchecked** for speed) → **Run investigation** | "A new synthetic case: 12 transactions, no customer metadata." |
| 10–25 s | stage trace, gauge **83 critical**, SC-01 hit | "SC-01 structuring: ten deposits of 42–50 million from ten senders. The account age and declared turnover were not provided — DALIL does not invent them: SC-03 and SC-06 say NOT EVALUATED and the recommendation is PROVISIONAL." |
| 25–45 s | note → click a transaction citation `[E#]` | "Every line cites evidence. Click a citation — the source transaction is highlighted in the table. The badges are separate: citation IDs exist, numbers and dates match the cited evidence, meaning NOT machine-verified." |
| 45–65 s | type analyst name + justification → **Escalate L2** | "The decision needs a name and a justification. The name is typed, not authenticated — we say so in the UI. Score and checks come from the server record." |
| 65–80 s | **reload the page** → Investigate | "Reload: the result and the decision come back from the server, by analysis id." |
| 80–100 s | **Export package** | "Export is built by the server. Two answers: integrity — hashes consistent; and match with this server's record. A hash is not a signature: someone holding the whole file can rewrite content and hashes — that is why the server-match check exists." |

If time allows / in Q&A: terminal `python scripts/verify_export.py <file>` → OK; edit one
amount → FAIL with the section name. (Tamper check is CLI-only, not in the UI.)

Fallbacks: tunnel down → `localhost:8000`. LLM down → pill says "LLM offline · template note
only"; nothing else changes. Demo laptop rebooted → `bash scripts/run_demo.sh`.

## 2:55–4:00 · Results (synthetic, reproducible: `eval/run_eval.py`)

"On the held-out synthetic test / novel-variant split: ensemble FPR 2.0% /
0.4% at band 50 with recall 99.7% / 99.2%; rules-only FPR
57.0% / 58.1%. Precision at an **assumed** 10% prevalence:
96.4% on novel — an assumption, not bank data.
LLM drafts, n=20: 0/20 drafts had zero check issues; citation IDs existed
95.0%; numbers matched cited evidence 20.0%; 2/20 truncated; latency p50
19 s on 4 CPU threads. That is why the **template** note is primary and the LLM draft
is labelled experimental. We do not claim hallucination-free output."

## 4:00–5:00 · What was hard / what we fixed

1. **Strict input**: `12abc`, `4,500` (ambiguous), unknown direction or channel, future dates
   are rejected with row numbers — never silently converted.
2. **Separate checks** for citation IDs, numbers/dates, completeness; meaning stays human.
3. **Server as source of truth**: each run has an analysis id; decisions and exports cannot
   take a score or evidence from the browser. Tests cover forged score, evidence, decision
   swapping and forged analysis ids.
4. Honest data note: the training parser misread 2.3% of synthetic amounts (all < 1 mln);
   fixed at inference, model not retrained, eval re-run.
We did **not** reuse code, data or weights from the Tahlil reference material (it has no licence file).

## 5:00–5:45 · Business & cost (assumptions)

"MKBANK FCC is a **proposed** pilot client, not a confirmed partner. No external AI API fee
per case — but hardware (~$55/month estimate) and analyst time remain; $0 API ≠ free. The
$30k/month saving is arithmetic on assumed volumes (4 000 alerts × 30 min × $15/h) — no pilot
has measured it."

## 5:45–6:30 · Pilot ask

"A 4-week pilot on anonymised real alerts inside the bank's own environment, measuring:
FPR at fixed recall, minutes per alert, and note-check pass rate on real cases. Production
needs a separate bank deployment, security review and model-risk validation."

## 6:30–7:00 · Close

"DALIL: evidence-linked scoring and notes, strict input, the analyst decides, and every
limitation is printed where it applies. Thank you."
