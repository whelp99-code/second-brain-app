# Why the 19 company candidates do not drain

Task: `TASK-SB-DRAIN-CAUSE-20261012`. Refs #30 and the earlier audit PR #65.
Host: `jm-omachy`. This proposal is independent of PR #65, based on master.

## Verdict

**The reader is working. These are received, unaccepted company candidates
whose confirmation/processing handoff has not been configured. They are not
19 actionable approvals waiting for the representative in JARVIS.**

`candidate` is the correct initial store state, but that state alone does not
prove normal human waiting. The active contexts contain no key allowed to
read/accept/reject/process a candidate, and none of the 19 is linked to an
existing JARVIS control request. Consequently no currently configured actor
can perform `candidate -> accepted -> processed_complete`.

This is an incomplete receive-and-list deployment, not evidence that a reader,
delivery timer, socket permission or old host path stopped working. Restarting
the reader or adding a drain timer with its list-only credentials cannot fix it.

## Current state and authority evidence

At **2026-10-12T14:53:01.304709Z**, one read-only company DB transaction found:

| Observation | Count / time |
| --- | --- |
| `candidate` / `accepted` / `rejected` / `processed_complete` | 19 / 0 / 0 / 0 |
| Receive receipts, all ages | 19 |
| First / last receive receipt | 2026-10-09T12:03:24.451Z / 2026-10-12T08:00:27.493Z |
| Read / accept / reject / mark_processed receipts | 0 / 0 / 0 / 0 |
| Non-null accepted / rejected / processed timestamps | 0 / 0 / 0 |

The two installed canonical configs are `mail-ms/config.json` and
`jarvis-reader/config.json` beneath the company-memory config directory.
Config values and identities were inspected only in memory, not recorded.

| Allowed operation across trusted keys | Key count |
| --- | --- |
| `receive` | 1 |
| `list_candidates` | 2 |
| `read`, `accept`, `reject`, `mark_processed` | 0 each |
| Unscoped trusted keys | 0 |

The Mail publisher intentionally receives only; the dedicated JARVIS accounts
intentionally list only. Neither operation accepts a candidate. The store
requires explicit acceptance before processing. The verifier rejects a
disallowed operation before database access
(`sb/company_memory_authority.py:175-180`).

## Real reader and approval location

`GET http://127.0.0.1:4173/api/v1/mail-candidates`, with a same-origin session
CSRF header retained in memory, returned **HTTP 200, SB `read`, count 19**
at **2026-10-12T14:53:52.013Z**. The existing candidate socket and web/dashboard
services were active. No failure or old host path was observed.

The actual browser page **`http://127.0.0.1:4173/finance-read`** shows:

- SB company-memory candidates: **19**.
- Native original-source read.
- Read-only; no candidate confirmation/change authority.
- **0** confirmation controls and **0** individual SB review rows.

It is a counter, not a place where the representative can approve those items.

The actual **`http://127.0.0.1:4173/approvals`** screen does exist.
Its owner-inbox API returned **4** visible control items:
`memory.outbox.dispatch` 2, `memory.confirm` 1, and
`memory.outbox.abandon-not-delivered` 1. Company processing operations: **0**.
These are not the 19 company candidates.

To verify linkage rather than infer it from names/counts, the running dashboard
PID's open file descriptors identified its actual DB,
`/var/lib/jarvis-svc/state/orca-jarvis/jarvis.sqlite`. A read-only transaction
attached the company DB using `mode=ro`, then compared candidate IDs internally
against all control-request argument/target JSON text values. Only counts were
returned: **19 company candidates, 0 linked to any control request**.
No candidate IDs, request summaries, bodies or digests were output.

Private, cropped browser evidence is retained at:

- `/home/jm/.omo/omonyang/.omo/evidence/TASK-SB-DRAIN-CAUSE-20261012/candidate-card.png`
- `/home/jm/.omo/omonyang/.omo/evidence/TASK-SB-DRAIN-CAUSE-20261012/approval-location.png`

The second capture is header-only, without approval records or identity values.
Task-owned browsers/profiles were closed and deleted. No approval was clicked.

An earlier development-route/selector inference suggested `/approvals` was
absent. Actual rendered QA disproved that inference: the screen exists, but
the company candidates are not delivered there. Deployed UI, not a development
route table or a transient missing DOM ID, is the evidence of record.

## Configuration and handoff correction proposal

Do not change Mail's receive-only key or JARVIS's list-only keys. Do not drain
by rejecting/acknowledging unseen candidates, widening the reader, issuing a
personal `memory.confirm`, or directly updating SQLite.

After Cursor review, the operator should:

1. **Provision a separate company processing context**, for example
   `~/.config/second-brain/company-memory/owner-processor/config.json`, mode
   `0600`, private directory `0700`. Keep the same company DB and isolation
   roots. Preserve the candidates' workspace, principal, project scope, policy
   revision and deletion fence. Give the processor its own agent/session
   context and a separately issued signing key; do not copy private Mail or
   reader keys into it.
2. Restrict that key explicitly:

   ```json
   {
     "operations": ["read", "accept", "reject", "mark_processed"],
     "source_systems": ["mail"]
   }
   ```

   This is the `key_scopes` entry, not a replacement for the complete trusted
   config. Store only the processor's public verification key there; its signer
   remains in the operator's separate authorized context.
   `source_systems` is a receive-operation fence in the current verifier, not
   an additional read/accept/process filter. The measured DB is Mail-only;
   keep it separate and preserve the existing workspace/access/deletion fences.
   The processor has neither `receive` nor `list_candidates` permission.
3. **Provide an explicit company review handoff.** Use the existing list-only
   path to select metadata privately, then the processor's signed `read` to
   review that candidate in an authorized company channel. A human decision
   invokes `accept` or `reject`; only a verified completed downstream result
   invokes `mark_processed`. Each request binds the exact operation/purpose,
   candidate and trusted context and returns its normal durable receipt.

   Existing commands are:

   ```bash
   sb-company --config ~/.config/second-brain/company-memory/owner-processor/config.json \
     < signed-read.json
   sb-company --config ~/.config/second-brain/company-memory/owner-processor/config.json \
     < signed-accept.json
   sb-company --config ~/.config/second-brain/company-memory/owner-processor/config.json \
     < signed-mark-processed.json
   ```

   The files must be actual freshly signed requests from that authorized signer;
   an unsigned example, stale authority or a receipt from a different candidate
   is not accepted. This task generated no real signer or request.
4. If JARVIS approval-inbox UX is required, **add a company-specific handoff
   and executor mapping** to that inbox. Provisioning the CLI context alone
   does not make the 19 appear in the existing personal-memory approval UI.
   Do not reuse `memory.confirm`: its contract addresses JARVIS personal-memory
   candidates, not these company records. That cross-product integration is
   not claimed as implemented by this configuration proposal.
5. Before activation, run one synthetic candidate through the selected owner
   path; verify list/receive accounts still cannot mutate. After separately
   authorized operation, count real mapped company review items and inspect
   accept/process receipts. A reader HTTP 200 or a falling counter alone does
   not establish successful company processing.

No missing timer can substitute for these missing authority and handoff
bindings. A periodic list poll only observes the same candidates.

## Verification and operational boundary

The real installed `sb-company` entry point was exercised on disposable
synthetic data, not on company records. An operation-scope probe tests that
receive/list-only keys refuse accept without mutation, an explicitly allowed
owner scope rejects process-before-accept, and accept/read/process complete
with durable receipts. The repository's packaged CLI smoke and related
company lifecycle/key-scope/reader tests verify the adjacent contract.

Observed CLI results: receive/list-only `accept` returned
`COMPANY_KEY_OPERATION_DENIED`; owner processing before acceptance returned
`MEMORY_CANDIDATE_NOT_ACCEPTED`; owner accept/process reached `accepted` and
`processed_complete`, with four durable receipts. The installed packaged
smoke also passed with personal data unchanged and temporary-fixture cleanup.
Final related verification: **60 passed**, lint clean, and **0 type errors,
0 warnings, 0 notes**. No existing test was changed or weakened.

No production data, config, keys, services, timers or permissions are changed
by this proposal. The 19 remain pending. There is no newly working company
approval screen, no deployed processor, and no automatic drain claimed.
The actionable correction is the separate processing context and review
handoff above; its activation remains with omonyang after Cursor review.
