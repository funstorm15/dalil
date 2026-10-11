# DALIL — AML investigation copilot (hackathon prototype, synthetic data)

**Proposed pilot client:** MKBANK Financial Crime Compliance — partnership **not** confirmed.
Context: Central Bank of Uzbekistan AML/CFT reporting.

> DALIL turns an alert case (CSV or queue) into one screen: an explainable 0–100 risk score,
> typology-rule hits linked to their transactions, and an investigation note built only from
> an evidence list — plus an optional **experimental** draft from a local open-weight LLM.
> The analyst decides. No external AI API is called.

**Live demo:** https://cornbread-left-licking.ngrok-free.dev — the presenter's laptop behind an
ngrok tunnel, **synthetic data only**, not a bank environment (first visit: click "Visit Site").

---

## 1. The problem

- Alert review is manual: scrolling transactions, transliterating UZ/RU names, matching
  typologies. Alert volume and minutes per alert used in §6 are **assumptions** — we have not
  measured them at a bank.
- On **our own synthetic benchmark**, a rules-only layer flags 57.0% of clean test
  cases and misses 20.9% of held-out laundering variants (§5).
- Banks restrict sending customer transaction data to external AI services, and any note that
  supports a filing must be traceable to the underlying transactions.

## 2. What DALIL does

Paste a CSV (or pick a synthetic demo case) → a live stage-streamed UI shows:

1. **Risk score 0–100** — 70% calibrated gradient-boosting model + 30% transparent scenario
   rules, banded low / medium / high / critical.
2. **Typology rules** SC-01 structuring … SC-06 turnover mismatch, each hit linked to its
   transactions. Rules that need missing metadata say **NOT EVALUATED**.
3. **Investigation note (template)** — assembled only from the evidence list; every line cites
   `[E#]`. Clicking a citation highlights and scrolls to the source transaction.
4. **Experimental LLM draft (optional)** — Qwen2.5-1.5B-Instruct (Apache-2.0) via llama.cpp on
   the same host. It can mis-state meaning; it is never the record. Drafts cut at the token
   limit are marked **INCOMPLETE**.
5. **Note checks, reported separately** — citation IDs exist · numbers, amounts (incl. "mln")
   and dates match the evidence cited in the same sentence · text complete · **meaning NOT
   machine-verified**. Checks are warnings; they do not block anything.
6. **Analyst decision** — requires a name (self-declared, **not** authenticated) and a
   justification; stored on the server against the `analysis_id` and input SHA-256.
7. **Export package** — built by the server from its own record (never from data posted by
   the browser): input + hash, model/ruleset ids, results, evidence, note + draft + checks,
   decision. Verification answers two separate questions: *integrity* (per-section SHA-256
   over canonical JSON) and *match with this server's record*. A hash is not a signature:
   whoever holds the whole file can rewrite content and hashes together.

## 3. Architecture

```
  CSV / queue ─▶ FastAPI (one host; demo = presenter's laptop, API bound to 127.0.0.1)
                  strict ingest → entity clusters (UZ/RU translit) → 49 features
                  → scenario rules SC-01..06 ─┐
                  → HistGB risk model ────────┴→ score (0.7·ML + 0.3·rules)
                  → evidence list → template note → note checks
                  → optional llama.cpp :8081 draft (local GGUF) → note checks
                  → analysis record (data/analyses/<analysis_id>.json)
                  → decision log (data/audit/audit.log, JSONL, not tamper-proof)
                  SSE stage stream ─▶ React SPA (queue / investigate / system)
  public demo: ngrok tunnel → 127.0.0.1:8000
```

No external AI API is called. We have **not** audited all outbound traffic of the host or the
tunnel. A production rollout needs a separate bank deployment, authentication, security and
egress review, DR and model-risk validation — out of scope for this prototype.
Design notes: [`docs/architecture.md`](docs/architecture.md).

## 4. Run it

```bash
make setup          # venv + pip + npm ci
make llm            # llama.cpp + Qwen2.5-1.5B GGUF (~1 GB, Apache-2.0)
cd frontend && npm run build && cd ..
bash scripts/run_demo.sh                 # llama + API (+ ngrok if configured) as systemd user units
RESTART_API=1 bash scripts/run_demo.sh   # after a code change
```

`run_demo.sh` uses *transient* user units: they restart on crash but **not** after a reboot —
run the script again. Without the LLM, everything works except the experimental draft.
Docker: the Dockerfile builds one image (API + SPA + LLM); mount
`-v dalil-analyses:/app/data/analyses -v dalil-audit:/app/data/audit` or analyses and
decisions are lost when the container is replaced.

### Input format (CSV)

| Column | Required | Accepted |
|---|---|---|
| `ts` | yes | `yyyy-mm-dd[ hh:mm[:ss]]`, `dd.mm.yyyy[ hh:mm]`, `dd/mm/yyyy[ hh:mm]`; not after today (Asia/Tashkent) |
| `amount` | yes | positive UZS: `43500000`, `43 500 000`, `45000000.50`, `4,5 млн`, `300 тыс`, optional `UZS`/`сум` |
| `direction` | yes | `in/out`, `credit/debit`, `приход/расход` |
| `counterparty_name` | yes* | non-empty (*or `from_name` + `to_name`) |
| `counterparty_kind` | no | `person`/`business` (empty → person, reported) |
| `channel` | no | `p2p, cash_in, cash_out, atm, card, pos, merchant, wire` (empty → `unknown`, reported) |
| `id` | no | if present: non-empty and unique |

Amount format is chosen explicitly: `strict` (default; a single `.` or `,` followed by exactly
three digits — `4,500`, `1.234` — is ambiguous and rejected), `dot-thousands` (`1.234.567,89`)
or `comma-thousands` (`1,234,567.89`). Bad rows are rejected (HTTP 422) with row numbers;
nothing is silently converted. Missing account age / declared turnover are **not invented**:
the affected rules are not evaluated, the model input is imputed with the training median (shown
in evidence and warnings) and the recommendation is marked **PROVISIONAL**.

## 5. Results (synthetic data — reproducible with `eval/run_eval.py`)

Report: [`eval/results/eval_report.json`](eval/results/eval_report.json). All numbers are on our
own synthetic casebook; ROC-AUC on synthetic data is optimistic. Re-run on 11 Oct with the
corrected amount parser (see Limitations 2).

| Metric | Test split | Novel-variant split ★ |
|---|---|---|
| Model ROC-AUC | 0.9945 | 0.9937 |
| Rules-only FPR | 57.0% | 58.1% |
| Rules-only recall | 91.7% | 79.1% |
| Ensemble FPR @ band 50 | 2.0% | 0.4% |
| Ensemble recall @ band 50 | 99.7% | 99.2% |
| Precision @ **assumed** 10% prevalence | 84.7% | 96.4% |

★ the novel split holds typology parameters never seen in training. Precision@prevalence
applies the measured TPR/FPR to an assumed 10% base rate — a planning assumption.

**Experimental LLM drafts** (Qwen2.5-1.5B Q4, n=20 held-out test cases, 4 CPU threads,
checked by `core/verifier.py`): 0/20 drafts with zero check issues; citation IDs existing
95.0%; numbers/amounts/dates matching the cited evidence 20.0%; unsupported
17, miscited 53, uncited 159 values in total; 2/20 truncated;
latency p50 19 s, p95 27 s. **Meaning is not measured.** This is why the
template note is primary. Template notes: 20/20 consistent by the same checks (expected —
they copy evidence text).

**Latency** (no LLM): pipeline p50 189 ms / p95 310 ms on a 16-core laptop in power-saver mode with `OMP_NUM_THREADS=1` (as `run_demo.sh` runs the API; with default OpenMP threads the same machine measured p50 830 ms). LLM draft latency above was measured on the same laptop.

**Failures** (published in the System tab): 5 false positives and 1 false
negatives at band 50 on the test split.

## 6. Pilot budget and payback (illustrative assumptions)

No bank has validated these costs or benefits. This is a planning scenario, not a quotation.

| Item | Assumption |
|---|---|
| External AI API fees | $0; hardware and people still cost money |
| One-off pilot | $6,000: 200 labour hours x $25 = $5,000; infrastructure $200; data review $500; reserve $300 |
| Monthly capacity value | 4,000 alerts x 5 minutes / 60 x $15/hour x 50% realisation = $2,500 |
| Monthly operating cost | $500 (support, infrastructure and maintenance allowance) |
| Net monthly benefit | $2,000; capacity value is not automatically a cash saving |
| Simple payback | 3 months after rollout; excludes the pilot duration |
| Sensitivity | At 2,000 alerts/month: $750 net/month and 8 months payback |

Start with a four-week workflow study using 50 authorised cases inside a bank. Measure
review time, corrections and missed evidence. This sample cannot establish a low FPR;
a larger independent holdout, data mapping, security review and model validation are required.

## 7. Data & licences

- **Synthetic casebook** (`data/generated/`, 3 880 cases, CC0): `data/generator/generate.py`,
  no real personal or bank data — [`DATA_CARD.md`](data/generated/DATA_CARD.md),
  [`LICENCE-DATA.md`](data/generated/LICENCE-DATA.md). Hand-written test fixtures in
  `tests/fixtures/` are synthetic too.
- **LLM**: Qwen2.5-1.5B-Instruct GGUF (Apache-2.0); **runtime**: llama.cpp b11541 (MIT).
- **Code**: MIT — `LICENSE`. No code, data or weights from other projects were reused.
- Ground-truth labels exist only for offline evaluation; `/api/queue` strips them.

## 8. Limitations

1. Synthetic ≠ real UZS flows; performance on bank data is unmeasured.
2. The model (`dalil-gbm-1.0.0`) was trained with a parser that read 2.3% of synthetic amounts
   (values like `"300.000"`, all < 1 mln UZS) 1000× too small. Inference reads them correctly;
   the model was not retrained for this release.
3. The LLM draft can be wrong in meaning (direction, typology, which evidence supports what)
   even when all checks pass, and in the eval it often states numbers without citations,
   cites the wrong evidence item, claims typologies that did not fire, or copies figures from
   the few-shot example in the prompt ("48.9 mln near the 50 mln threshold"). It is
   experimental and never the record.
4. Note checks are warnings, not a gate. Meaning is never machine-verified.
5. Analyst names are self-declared; the API has no authentication (demo tier).
6. The decision log is an ordinary file, not tamper-proof. Export hashes are not signatures.
7. Imputed metadata makes the score provisional; no cross-case ownership graph; UZS only.
8. CPU demo tier: LLM drafts take p50 19 s, p95 27 s on this laptop (eval, n=20).

## 9. Repo map

```
backend/app/core/   ingest (strict validation), normalize, features, scenarios, riskmodel,
                    pipeline, verifier, llm, store (analysis records), audit, export
backend/app/api/    FastAPI routes incl. SSE /api/analyze, /api/decision, /api/export(/verify)
frontend/           React + TS SPA (queue / investigate / system)
data/generator/     synthetic casebook generator (seed 20261010)
scripts/            train, build_queue, download_llm, run_demo.sh, verify_export.py
eval/               run_eval.py → eval_report.json
tests/              91 pytest tests (unit, API, regression for the release fixes)
docs/submission/    deck (PPTX/PDF), 7-minute defence script, Q&A
```

## 10. Track & team

FinTech / AI in Finance. Built solo in the hackathon window, with AI coding assistance;
synthetic-data declaration per challenge rules.

## Final submission materials

Use `docs/submission/DALIL-FINAL.pdf` (or editable `DALIL-FINAL.pptx`) for submission.
The earlier `DALIL-hackathon-2026.*` files are archived drafts and are superseded.
Use `docs/submission/defence-script.md` for rehearsal and `DALIL-demo-backup.mp4` as a silent backup.
No final dashboard submission is performed by this release preparation.
