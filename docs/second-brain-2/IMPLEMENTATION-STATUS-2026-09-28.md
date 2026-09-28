# R1 implementation status — 2026-09-28

Tree: `518c7b3dfe4182c232a18f7994aca9b59720488e` (`merge: R1 phase 3 lane l3c`) in `/home/jm/orca/projects/second-brain-app-wt/r1-l4b`.
This file separates what that tree contains from what still needs an operator, a device, or a later lane. It does not mark production done.

## Ready to continue in checkout (code already on this base)

Phase 1–3 lanes are ancestors of this commit (HEAD subject is the L3.C merge). Inventory rows those lanes own are implemented in this tree insofar as their modules exist here. This status file does not re-litigate their tests; the full suite log is the regression citation (2527 passed, 3 skipped, 0 failed).

P01 contract work can continue from this tree: life-event sidecar, personal-observation sidecar, and scan-receipt sidecar are present. Existing MCP/scoped sidecars match `bdaa363`.

No new feature flag is required. Absent `[life]` keys keep flags off.

## This lane (L4.B), published with this commit

| Row | State | Evidence |
| --- | --- | --- |
| P00-1 | DOC published | identifier table in `baseline/R1-BASELINE-2026-09-28.md` and `.json`. Installed column NOT_RUN. |
| P00-2 | DOC published | ADR-R1-001, ADR-R1-002, flag and adapter inventory in the baseline. Live source counts NOT_RUN. |
| P00-5 | DOC published | baseline, both ADRs, risk register, evidence classification, this status file. AC-24 checkout pair recorded with exit codes and log paths. Real-model / real-server / real-device NOT_RUN. |

## Not in this tree (later R1 lanes or out of checkout)

| Item | Why it is not "done" here |
| --- | --- |
| L4.A `personal-memory-v1` / `sb_recall` profile | `contracts/second-brain-personal-memory-v1.json` absent. JARVIS loader registration stays GATED-JARVIS even after L4.A. |
| L4.C acceptance harness | `tests/test_life_acceptance_r1.py` absent. AC-01/03/04/05/09/15/16/18 citations for that harness are not available yet. |
| P00-3 isolated production restore | GATED-PROD. Needs a real backup archive and an approved host. |
| P00-4 device spike | GATED-DEVICE. |
| P03-T19 mail donor | GATED-JARVIS (Mail Intelligence repo). |
| P03-T24 live backlog drain | GATED-PROD. Coverage receipts in code are not that proof. |
| P07-1 scheduler registration, P07-2 provider channel | GATED-PROD. Unit templates are not registration. |
| P04-1, P04-3, P04-T43, P06-1, P06-2, P06-4, P07-3, P16-17i, P16-17a | GATED-DEVICE. |

## Explicit non-claims

- Document publication does not change product implementation state of gated rows.
- 2xx from a notification transport is not delivery success.
- A green checkout suite is not an installed-wheel match and not a device pass.
- `origin/master` was not fetched. Divergence is against the local tracking ref only.
