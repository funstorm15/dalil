# DALIL V2 — project and demo guide

DALIL is a synthetic AML (anti-money-laundering) investigation prototype. It helps an analyst prioritise alerts, inspect the transactions behind a risk score, prepare an evidence-linked note, and record a human decision. It does not establish that a crime occurred or replace bank compliance staff.

## What each screen means

- **Alert queue:** synthetic cases ordered by risk. Open a case to investigate it.
- **Investigate:** select a demo case or paste/upload a CSV. The built-in template contains 12 synthetic transactions. Amount parsing is strict; missing customer metadata produces a provisional result.
- **Pipeline trace:** shows processing stages and their elapsed times.
- **DALIL score:** a 0–100 prioritisation score combining a calibrated model (70%) and scenario rules (30%). It is not the probability that a person committed a crime.
- **SC-01–SC-06:** cash structuring, rapid pass-through, young-account fan-in, crypto off-ramp patterns, counterparty cycles, and inflow/declared-turnover mismatch. A hit is a reason to review. “Not evaluated” means required information was missing.
- **Investigation note:** the primary note is assembled from evidence. E1, E2, etc. are citations; clicking a transaction citation opens its table page and highlights its row.
- **Experimental local-LLM draft:** optional slower text generation on this computer. Citation and numerical checks do not verify meaning; an analyst must review it.
- **Score attribution:** shows which features move this case's score relative to typical values. It is an explanation of the model, not proof of causation.
- **Transactions:** 10 rows by default, selectable 15; First/Previous/Next/Last navigate the complete analysis. Uploads remain capped at 2 MB. This release does not support million-row ingestion.
- **System & evidence:** model, data, evaluation and limitations information. Benchmark results are synthetic, not bank validation.
- **Light/Dark:** header switch, remembered in this browser.

## Decisions and export

Enter an analyst name and a justification before recording a decision. The name is self-declared, not authenticated.

- **Dismiss:** record that this alert does not require further action based on the review.
- **Escalate L2:** refer the case for a second-level analyst review.
- **File STR:** STR means Suspicious Transaction Report. In this prototype the button records that decision in the demo log; it does not send a report to a regulator.
- **Request info:** record that more information is needed before deciding.
- **Export package:** download the server-built JSON with analysis, evidence, checks and decisions. “Integrity consistent” verifies hashes; “server record match” compares against this server. Hashes are not a digital signature or tamper-proof storage.

Use synthetic data only on the public demo. There is no production authentication or regulated reporting integration.

## Short pitch

“DALIL helps AML analysts move from an alert to a documented decision. It combines model scoring with transparent rules, links the investigation note to transaction evidence, and keeps the analyst in control. V2 adds a clearer Casebook interface, light and dark themes, and 10/15-row transaction pages. Our results are measured on synthetic data; real-bank validation remains future work.”

## Demo sequence

1. Investigate → New CSV → load template.
2. Uncheck experimental LLM for a quick, predictable demonstration.
3. Run investigation: expect 83.4 / critical, SC-01 hit, SC-03/SC-06 not evaluated, and a provisional recommendation.
4. Explain the evidence-linked note. Navigate page 2, switch to 15 rows, and click a transaction citation.
5. Use an explicitly synthetic analyst name and reason if demonstrating a decision.
6. Reload and reopen Investigate to restore the server-backed result; export and show the two verification checks.

The backup MP4 is a silent, edited screenshot walkthrough, not a continuous recording or a latency measurement.
