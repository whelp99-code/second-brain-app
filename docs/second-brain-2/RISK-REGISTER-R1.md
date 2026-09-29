# R1 risk register — 2026-09-28

Checkout: `518c7b3dfe4182c232a18f7994aca9b59720488e` on `sb2/r1/l4b`.
Severity is relative to continuing R1 code work, not a production outage report. Live impact is unmeasured.

| Id | Risk | Evidence | Status | Blocks |
| --- | --- | --- | --- | --- |
| R-01 | HEAD and `origin/master` have diverged (13 / 38). Integrating against the wrong tip drops either remote commits or R1 lanes. | `git rev-list --left-right --count origin/master...HEAD` = `13 38`. Tracking ref not fetched this run. | open | any claim that this branch is the GitHub tip |
| R-02 | Installed Ubuntu wheel identity is unknown. Package version `1.0.7` is the checkout, not a host install. | installed column NOT_RUN | open / GATED-PROD | production migration, cutover |
| R-03 | No isolated production restore has been run. A SQLite copy is not a certified backup. | P00-3 GATED-PROD; ADR-R1-001 | open | operational data migration |
| R-04 | Real Phone History, TLS, Mac and iPhone Obsidian paths are unverified. String-level Mac contract tests are not device closure. | P00-4 GATED-DEVICE | open | AC-06/22 device claims |
| R-05 | Live source counts, failure, quarantine, and backlog numbers are unknown. | GATED-PROD; adapter ids are repo inventory only | open | P03-T24 continuous-ingestion proof |
| R-06 | Real model install and egress under provider failure are not measured on a live provider. Checkout harnesses are not that measurement. | real-model NOT_RUN | open | P10 live-provider acceptance |
| R-07 | systemd timers exist as templates only. Approving them on the live host is a separate gate. | `deploy/systemd/`; P07-1 NOT_RUN | open | production schedule acceptance |
| R-08 | `second-brain-web.service` is `Type=simple`. A reader can mistake that for the forbidden resident queue. | unit file; ADR-R1-002 | accepted distinction | do not add a second in-process queue "because web already runs" |
| R-09 | `sb/store/AGENTS.md` still says ledger schema 5; code says 6. | read of both on this tree | open doc drift | do not migrate from the AGENTS sentence |
| R-10 | Plan AC-24 expected count 2428 passed is stale. This tree measured 2527 passed, 3 skipped, 0 failed. | `/home/jm/.cache/sbt/l4b-logs/pytest-full.log` | recorded | do not copy the plan number into evidence |
| R-11 | Literal section-5 pipeline-import `rg` matches a docstring and AGENTS prose, so the command as written is non-zero even with no forbidden import. | `coupling-rg.log` | recorded, not a product defect | gate authors should exclude comments; this lane cannot edit those files |
| R-12 | `personal-memory-v1` and `tests/test_life_acceptance_r1.py` are absent. Phase 4 code lanes are not in this baseline commit. | `ls` miss | expected | do not mark L4.A / L4.C done from this document |
| R-13 | Phone History pytest and `npm run check` were not run in this lane's verify set. Obsidian `npm test` was. | logs | partial | do not cite phone-history or syntax-check as passing here |
| R-14 | Notification 2xx can be reported as delivery. Code distinguishes `transport_accepted` from device receipt, but no provider was contacted. | `sb/life_delivery.py`; real-server NOT_RUN | open for live channel | P07-2/P07-3 |

No row above is closed by publishing this file. Closed-by-code items that later lanes already merged are listed in `IMPLEMENTATION-STATUS-2026-09-28.md` and are still not production evidence.
