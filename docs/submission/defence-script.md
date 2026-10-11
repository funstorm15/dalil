# DALIL — 7-minute defence script (FinTech track) + Q&A

Live demo budget: **≈100 s**, minute 1:15 → 2:55. Demo case: **New CSV → "load template"**
(12 synthetic transactions, no subject metadata). Verified on the release build: score
**83.4 / critical**, **SC-01 structuring hit** (10 deposits of 42–50 mln UZS from 10 senders),
SC-03 and SC-06 **NOT EVALUATED** (metadata missing), recommendation **PROVISIONAL**.

Before the slot, open https://cornbread-left-licking.ngrok-free.dev and run the template
case once. The live demo serves V2 (Casebook UI, light/dark themes, 10/15-row pages).
Local fallback: http://127.0.0.1:8012. Keep the API, LLM and ngrok processes running.
After reboot: start the LLM with `make llm-serve`, start the API with
`bash scripts/run_demo.sh`, then start ngrok against port 8012. Do not run the V1 launcher.
The included V2 backup MP4 is a silent, edited walkthrough made from actual UI screenshots,
explicitly labelled NOT continuous video. It supports the live demo, not a substitute
for a measured end-to-end timing demonstration.


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
**experimental draft** — no external AI API is called. Supported numerical formats are checked against
the evidence cited in the same sentence; the **meaning** is not machine-checked — that is the analyst's job.
The analyst decides; the server keeps the decision bound to that exact analysis and input
hash, and exports a package it builds from its own record."

## 1:15–2:55 · LIVE DEMO (≈100 s) — cues

| t | screen | say |
|---|---|---|
| 0–10 s | Investigate → **New CSV** → **load template** → (LLM draft box **unchecked** for speed) → **Run investigation** | "A new synthetic case: 12 transactions, no customer metadata." |
| 10–25 s | stage trace, gauge **83 critical**, SC-01 hit | "SC-01 structuring: ten deposits of 42–50 million from ten senders. The account age and declared turnover were not provided — DALIL does not invent them: SC-03 and SC-06 say NOT EVALUATED and the recommendation is PROVISIONAL." |
| 25–45 s | note → click a transaction citation `[E#]` | "Every line cites evidence. Click a citation — the source transaction is highlighted on the correct table page. Pages show 10 or 15 rows; this is display pagination, not million-row ingestion. The badges are separate: citation IDs exist, numbers and dates match the cited evidence, meaning NOT machine-verified." |
| 45–65 s | type analyst name + justification → **Escalate L2** | "The decision needs a name and a justification. The name is typed, not authenticated — we say so in the UI. Score and checks come from the server record." |
| 65–80 s | **reload the page** → Investigate | "Reload: the result and the decision come back from the server, by analysis id." |
| 80–100 s | **Export package** | "Export is built by the server. Two answers: integrity — hashes consistent; and match with this server's record. A hash is not a signature: someone holding the whole file can rewrite content and hashes — that is why the server-match check exists." |

If time allows / in Q&A: terminal `python scripts/verify_export.py <file>` → OK; edit one
amount → FAIL with the section name. (Tamper check is CLI-only, not in the UI.)

Fallbacks: tunnel down → `localhost:8012`. LLM down → pill says "LLM offline · template note
only"; nothing else changes. Demo laptop rebooted → `bash scripts/run_demo.sh`.

## 2:55–4:00 · Results (synthetic, reproducible: `eval/run_eval.py`)

"On the held-out synthetic test / novel-variant split: ensemble FPR 2.0% /
0.4% at band 50 with recall 99.7% / 99.2%; rules-only FPR
57.0% / 58.1%. Precision at an **assumed** 10% prevalence:
96.4% on novel — an assumption, not bank data.
Historical LLM drafts before DEMO relabelling, n=20: 0/20 drafts had zero check issues; citation IDs existed
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

## 5:00–5:45 · Business & cost (all figures illustrative)

"Our proposed owner is the MKBANK FCC alert-investigation desk; no partnership is confirmed.
A pilot budget of $6,000 assumes 200 labour hours at $25, $200 infrastructure, $500 data review
and $300 contingency. At 4,000 alerts monthly, five minutes saved, $15 per hour and 50% useful
realisation, capacity value is $2,500 monthly. After $500 operating cost, the scenario yields
$2,000 net and three months payback after rollout. At half the volume, payback rises to eight
months. These are assumptions, not measured savings or a commercial quote."

## 5:45–6:30 · Pilot ask

"We propose a four-week workflow pilot with 50 authorised cases inside the bank, measuring
review time, factual corrections and missed evidence. Fifty cases cannot establish a low FPR;
detection quality needs a larger independent holdout. Production requires data mapping,
authentication, secure storage and model validation. Our current differentiation is a compact
local workflow with UZS and RU/UZ handling; we do not claim a proven barrier to copying."

## 6:30–7:00 · Close

"DALIL: evidence-linked scoring and notes, strict input, the analyst decides, and every
limitation is printed where it applies. Thank you."
