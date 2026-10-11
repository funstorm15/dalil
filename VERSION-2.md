# DALIL Version 2 — Casebook release

Source snapshot: V1 commit 765e25d6a7e9bf41f4ff09f4c330d99f9a679960.
V1 remains at /home/funstorm/Work/dalil. Preserve that folder unchanged.
The user has now authorized switching the existing public demo URL to V2.
V1 is preserved by the v1-hackathon-submitted tag; this release updates the existing repository.

This directory contains independent copies of code, synthetic data, model weights,
LLM binaries and installed dependencies. Git objects are independent, runtime histories are excluded from version control. Secrets, old runtime
histories and private work archives were not copied.

Start V2 locally:

    npm run build --prefix frontend
    bash scripts/run_demo.sh

Open http://127.0.0.1:8012. Vite development port is 5174 and proxies to 8012.
No ngrok or systemd operations run. V2's optional LLM address is 18081, separate
from V1's 8081. No V2 LLM is started automatically; template notes work without it.
Submission materials in docs/submission are updated for V2.

## First change

Transaction table: 10 rows by default, 10/15 selector, First/Previous/Next/Last,
visible range and page count. Evidence clicks automatically open the correct page
and highlight the transaction, including repeated clicks on the same evidence.
A new analysis starts at page 1. Page-size changes retain the first visible row.
Scores, rules, decisions and exports continue to use the complete analysis.

This is display pagination. CSV parsing, analysis and transfer still use the whole
case, with the existing 2 MB CSV cap. Million-row processing is not supported or
claimed. It needs separately designed ingestion, server pagination and profiling
of the entity-resolution/feature calculations before raising upload limits.

UI direction C (Casebook) selected: warm paper surfaces, olive accents, editorial serif headings, side navigation, and evidence-led sections. Applied only to V2; desktop and narrow layouts retain all existing workflows.

The header Light/Dark mode switch saves the choice in V2-specific browser storage. On a first visit, it follows the system appearance. Both modes use the Casebook palette.

## Public activation

The existing URL https://cornbread-left-licking.ngrok-free.dev now routes to V2
on port 8012 through the existing ngrok agent. Public HTML, assets and API were
verified. V2's independent LLM is running on port 18081.

V1 files are unchanged. Its unmanaged API/LLM processes are still running locally;
they no longer serve the public URL. The public release is maintained in the existing repository.

The ngrok process was launched by an earlier Codex session, not systemd.
The active endpoint was changed using the local agent tunnel API. Restarting that
old ngrok command can restore its old destination; do not rerun the V1 launcher.
For a subsequent activation, `bash scripts/activate_v2.sh` starts a managed V2 API
on port 8013 and retargets the running ngrok agent. The agent must already be up.
`scripts/switch_endpoint.py --port 8012` (or 8013) verifies V2 before switching,
saves the old endpoint settings, verifies the public build, and rolls back on failure.
Local servers and the ngrok agent must remain running for the public URL to work.
