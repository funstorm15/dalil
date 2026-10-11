# DALIL — Q&A prep

Rule: answer in one breath, then the caveat. Never upgrade an assumption into a measurement.

## Metrics & data

**Q: Is ~0.99 AUC real?**
Held-out **synthetic** data — optimistic by construction. The rows we stand behind are the
novel-variant split (typology parameters not seen in training): ensemble FPR 0.4%,
recall 99.2%. Real-data performance is unmeasured.

**Q: Where does the rules-only FPR come from?**
Our own rule layer on our own synthetic test set (57.0%; novel 58.1%).
A baseline for the demo, not an industry or bank statistic.

**Q: Precision 96.4%?**
Measured TPR/FPR applied to an **assumed** 10% base rate. Planning assumption, not bank data.

**Q: Does the LLM hallucinate?**
Yes, it can. On n=20 held-out cases the 1.5B draft had zero check issues in 0/20;
numbers matched cited evidence 20.0%. Typical failures we saw: numbers without a
citation, the wrong [E#], typologies that did not fire, and figures copied from the few-shot
example in the prompt. That is why the primary note is a template built only from evidence and
the LLM draft is labelled experimental. Even a "consistent" draft can
be wrong in meaning — that is not machine-checked.

**Q: What exactly does the checker check?**
(1) every [E#] exists; (2) every number, amount (incl. "mln") and ISO date in a sentence
matches the evidence cited in that same sentence, within the rounding used; (3) the draft was
not cut at the token limit. Meaning: not checked. These are warnings — they do not block.

**Q: Earlier numbers said "citation precision 0.95"?**
That metric only measured whether citation IDs existed and a narrow number check missed
"mln"-formatted amounts. We replaced it with separate statuses and re-measured.

**Q: Data issue you found?**
The training-time parser read 3 196 of 139 534 synthetic amounts like "300.000" as 300 UZS
instead of 300 000 (all < 1 mln). Fixed at inference; model not retrained for this release;
eval re-run with the corrected parser.

## Product

**Q: Production-ready?** No. Production needs a separate bank deployment, authentication,
security and egress review, DR and model-risk validation.

**Q: MKBANK is your partner?** A **proposed** pilot client; no partnership is confirmed.

**Q: Is the live URL inside a bank?** No. A laptop behind an ngrok tunnel, synthetic data only.

**Q: "No data leaves"?** What we can say: the LLM runs locally and no external AI API is called.
We have not audited all outbound traffic of the host or the tunnel.

**Q: $0 cost?** $0 external AI API fees. Hardware (~$55/month estimate) and people cost remain.
The $30k/month saving is an assumption-based model, not a measurement.

**Q: LLM down?** The template note is unaffected; the UI says "LLM offline · template note
only" and the draft card says no draft.

**Q: What if the user types garbage?** 422 with row numbers: ambiguous amounts ("4,500"), junk
("12abc"), unknown direction/channel/kind, duplicate ids, future dates, missing columns.
Missing account age / turnover: not invented — rules not evaluated, model input imputed with
the training median, recommendation marked PROVISIONAL.

## Audit & export

**Q: Who is the analyst?** A typed name. Not an authenticated identity.

**Q: Is the decision log an audit trail?** It is an ordinary JSONL file opened in append mode.
Not tamper-proof, not immutable. Each line carries the analysis id, input hash and result hash.

**Q: What does the export hash prove?** Integrity relative to the stored hashes. Someone with
the whole file can rewrite content and hashes together — integrity then passes. The second
check, "matches this server's record", catches that while the server record exists. Not a
signature. Checking an edited file is CLI-only: `python scripts/verify_export.py file.json`.

**Q: Could the browser fake a score?** No: decisions and exports take only an analysis id; the
server uses its stored result. Tests cover forged score/evidence/decision/analysis id.

## Engineering

**Q: Entity resolution?** Union-find on account/name/phone with guards: surname-only and
prefix names (Temur/Temurbek) do not merge; an initial merges only if it resolves to exactly
one person in the case.

**Q: Tests?** 91 pytest tests + a browser end-to-end run (new CSV → evidence → decision
→ reload → export → verify; second case; bad input; LLM down).

**Q: Did you copy the Tahlil reference?** No. It has no licence file; no code, data or weights
were reused, and its standardized size indices are not mixed with UZS amounts.

**Q: Biggest open risk?** Synthetic-to-real drift and model-risk validation — pilot questions.
