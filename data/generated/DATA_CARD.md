# DALIL synthetic casebook — data card

| | |
|---|---|
| **Dataset** | `cases_train.jsonl`, `cases_test.jsonl`, `cases_novel.jsonl`, `cases_demo.jsonl` |
| **Generator** | `data/generator/generate.py` (deterministic, `seed=20261010`) |
| **Purpose** | Train and evaluate the DALIL risk model and rules layer; drive the demo UI queue |
| **Licence** | CC0 1.0 (public domain dedication) — see `LICENCE-DATA.md` |
| **Real personal data** | **None.** Every person, company, account, phone and memo string is generated. |
| **Real bank data** | **None.** No MKBANK or Central Bank systems were used or accessed. |

## What is simulated

Per-case records model the input of an AML alert-investigation desk at an Uzbek bank:

- **Subject**: account id, customer name (UZ-cyrillic / latin / RU mixes), legal-entity flag,
  account age, declared monthly turnover, branch.
- **Transactions** (~39 per case): UZS amounts with realistic noise, direction, counterparty
  (person / sole-proprietor / LLC / bank), channel (`p2p`, `cash`, `card`, `wire`, `crypto`),
  multilingual memos (`UZ/LAT/CYR/RU/EN`), phone numbers, and **messy real-world formatting**
  (`"0,5 млн"`, `43.500.000`, `dd.mm.yyyy HH:MM`, `+998 (90) 123-45-67`, blank fields).

## Labelled typologies (positive cases)

Each injected typology corresponds to a scenario rule the rules layer can also fire on
(`backend/app/core/scenarios.py`), plus subtler variants only the model learns:

| Code | Typology | Share of positives |
|---|---|---|
| SC-01 | Structuring / smurfing just under the 50 mln UZS reporting threshold | 25% |
| SC-02 | Rapid pass-through (in→out within hours, minimal retention) | 20% |
| SC-03 | Money-mule behaviour (young account, many small in-flows) | 15% |
| SC-04 | Round-sum / gamed-KYC turnover mismatch vs declared activity | 15% |
| SC-05 | Crypto-bridge flows (fiat↔USDT via P2P channels) | 15% |
| SC-06 | Layering through cash-intensive trade counterparties | 10% |

Clean cases include salary inflows, small trade, remittances, agriculture and services —
several deliberately "near-miss" the rules (many sub-threshold inflows that are legitimate)
so the rules layer's high false-positive rate is honestly measurable.

## Splits

| File | Cases | Positives | Notes |
|---|---|---|---|
| `cases_train.jsonl` | 1 800 | ~50% | Model fitting + calibration |
| `cases_test.jsonl` | 600 | ~50% | Same generative process, held out |
| `cases_novel.jsonl` | 600 | ~50% | **Held-out typology parameters** (different amounts, timing, memo language mix) — measures generalisation, not memorisation |
| `cases_demo.jsonl` | 80 | mixed | Feeds the demo queue served by the API |

Ground-truth labels are **never** served by the API (stripped in `/api/queue`) —
they exist only for offline evaluation, mirroring production where no labels exist.

## Known limitations (state these in the pitch)

1. **Synthetic ≠ production.** Real UZS flows have seasonal payroll patterns, mobile-app
   outages and branch-level habits the generator does not model. Expect ~1–3 pts of metric
   drift on real data; the pipeline is designed so re-training on real labelled data is one
   script (`scripts/train.py`) plus a JSONL swap.
2. **ROC-AUC on this corpus is optimistic** (~0.99) because injected patterns are cleaner
   than real laundering. The honest operational numbers are on `cases_novel.jsonl` and the
   rules-only false-positive rate (~57%).
3. **No beneficial-ownership graph.** Counterparty clusters are name/phone-resolved within
   a single case, not across the bank's full customer base.
4. **Currency is UZS-only** in the generator; FX and hawala corridors are out of scope.

## Regenerating

```bash
python data/generator/generate.py   # writes data/generated/*.jsonl + dataset_meta.json
python scripts/build_queue.py       # demo queue for the UI
```

## Amount-format convention (read this before re-using the files)

Messy amount strings use the generator's convention: `.` groups thousands (`"1.234.500"`,
`"300.000"` = 300 000 UZS), `,` is the decimal mark (`"4,5 млн"`), spaces group thousands
(`"43 500 000"`). The pipeline reads casebook records with `amount_format = dot-thousands`
(`backend/app/core/ingest.py`). Known issue: the parser used to train
`model/dalil_model.joblib` (10 Oct) read single-group values such as `"300.000"` as 300 UZS —
3 196 of 139 534 amounts (2.3%, all below 1 mln UZS). Inference now reads them correctly; the
model was not retrained for this release, and the eval report was re-run with the corrected
parser.

## Explicit demo identities (11 October 2026)

All bundled person/company names now use DEMO labels. Accounts and phone fields use non-routable DEMO-ACCOUNT / DEMO-PHONE tokens. They are not real-world identifiers. Stable labels preserve entity relationships within each case. The 3080 supplied cases retain identical 49 inference features and rule outputs after migration; see eval/results/privacy_validation.json. The published metrics use these supplied files. The updated generator emits explicit demo labels for future datasets; regenerating a different dataset requires reevaluation. Existing training weights were not retrained. LLM and latency measurements were made before renaming and are historical.
