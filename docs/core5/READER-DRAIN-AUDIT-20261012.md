# SB candidate reader drain audit

Task: `TASK-SB-READER-DRAIN-20261012`. Refs #30.
Host: `jm-omachy`. This is an audit and configuration/monitoring proposal,
not a deployed drain or a claim that pending candidates have been processed.

## Measured state

The company database was inspected in one read transaction with `mode=ro` and
`PRAGMA query_only=ON`, at **2026-10-12T14:21:47.327224Z**. The preceding
24-hour window starts at 2026-10-11T14:21:47.327224Z.

| Observation | Count / time |
| --- | --- |
| Pending candidates, all ages | 19 |
| Pending candidates first received in the last 24 hours | 18 |
| Receive receipts in the last 24 hours | 18 |
| Accepted / rejected / processed candidates | 0 / 0 / 0 |
| Read / accept / reject / mark_processed receipts in the last 24 hours | 0 / 0 / 0 / 0 |
| Processing-operation receipts, all ages | 0 |
| Pending candidates without a receive timestamp | 0 |
| Oldest pending first receive time | 2026-10-09T12:03:24.451Z |
| Oldest pending age at observation | 267502.876 seconds (74h 18m 22.876s) |

The database contains `company_memory_candidates` and
`company_memory_receipts`, with no separate reader-processing table. Candidates
have no creation timestamp. The first `receive` receipt joined on **both**
`workspace_id` and `candidate_id` supplies age provenance. Receipt counts and
distinct pending-candidate counts are separate; another receive receipt must
not reset a candidate's age or count it twice.

## Real JARVIS read proof

The HTTP surface is JARVIS **`GET /api/v1/mail-candidates`**, not the SB web
server. It delegates to the dedicated signed, list-only Unix-socket reader.
No query parameters are permitted. The HTTP session/CSRF token stays in
memory; neither it nor reader credentials are included in evidence.

The executed JS HTTP-client scenario was:

```javascript
const origin = "http://127.0.0.1:4173";
const sessionResponse = await fetch(`${origin}/api/v1/session`, {
  signal: AbortSignal.timeout(10000),
});
const session = await sessionResponse.json();
const response = await fetch(`${origin}/api/v1/mail-candidates`, {
  headers: { Origin: origin, "x-jarvis-csrf": session.csrf_token },
  signal: AbortSignal.timeout(20000),
});
const body = await response.json();
console.log({
  status: response.status,
  observed_at: body.observed_at,
  sb: { state: body.sb?.state, candidate_count: body.sb?.candidate_count },
});
```

Observed at **2026-10-12T14:23:06.517Z**:

```json
{
  "status": 200,
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  "schema_version": 1,
  "proof_level": "native-read",
  "sb": { "state": "read", "candidate_count": 19 }
}
```

PASS requires **HTTP 200 AND `sb.state == "read"`**, not status alone:
the route can return 200 with an unconnected reader. No row identifiers,
workspace values, content, credentials, customer data or amounts were captured.
Response bodies were consumed and transient session/response bindings cleared.
No QA server or browser was started; existing services were not restarted.

## Cause and correction proposal

The dedicated reader works after the host move. Its two configured reader
keys are restricted to `list_candidates` for Mail. Listing deliberately
does not create a receipt, accept a candidate, or mark it processed:
see `sb/company_memory_reader.py` and `sb/company_memory_cli.py`.
Consequently, **zero processing receipts does not mean zero successful reads**.
The observed backlog is real, but a successful read is not a drain.

The current path has no state-transition consumer: the JARVIS
`src/integration/sb-company-candidate-reader.ts` projects a count from the socket;
`src/dashboard/mail-candidates-routes.ts` exposes that read, and the dashboard
card reads on mount. Those components neither consume candidate contents nor
transition SB candidates. SB requires an explicit `accept` before
`mark_processed` (`CompanyMemoryStore.accept` / `mark_processed`).
JARVIS's own `memory_candidates`/outbox pipeline is a separate store, not
evidence that these company candidates were processed.

The proposed operational correction is to separate the two acceptance signals:

1. Keep the current JARVIS dedicated-reader descriptor and list-only scopes.
   Its live read passed; there is no evidence supporting credential rotation,
   broader permissions, or a socket/config change.
2. Register the outstanding 19 candidates with a **separate processing owner**.
   That owner must first define and verify the downstream durable result,
   then use its own explicitly authorized accept/process path. Reader keys
   must not acquire mutation privileges. No candidate is cleared, rejected or
   acknowledged merely to make the backlog metric zero.
3. Treat native-read availability and processing backlog as independent
   operational checks. Reader HTTP success is already verified; backlog
   remediation remains an operator-owned action after Cursor review.

There is no safe configuration switch that turns this list-only reader into
a processing consumer. If automatic processing is desired, a separately
scoped consumer implementation and its authority/downstream-result contract
are required; this PR does not invent that contract or activate it.

## Recurrence-monitoring proposal

No candidate-drain monitor was found in the observed user timers, or in the
request-driven reader source. This is a bounded observation, not a claim
about every external scheduler. Add a **jm-owned, read-only oneshot monitor**
on a proposed 15-minute systemd user timer after review. It is independent
of the server, which gains no watcher, queue or event bus.

The included executable query is `deploy/company-reader-drain.sql`:

```bash
sqlite3 -readonly -json \
  /home/jm/.local/share/second-brain-company/mail-ms/company.db \
  < deploy/company-reader-drain.sql
```

The real CLI run at **2026-10-12T14:25:29.925Z**, exit 0, reproduced 19 pending,
18 pending received in the preceding 24 hours, 18 receive receipts, 0 processing
receipts, and the same oldest receive timestamp. It emitted `monitor_state:
"stale"` and oldest age 267725.474 seconds. This is a successful detection of
backlog, **not a healthy-drain result**.

The query accepts optional `:observed_at` for deterministic replay and uses
SQLite time arithmetic, not lexical timestamp comparison. It emits one
aggregate row, with no row payloads or identities. It includes accepted
but unprocessed candidates; excludes rejected/processed candidates; and
reports missing, malformed or future receipt provenance as unknown. A missing
database/schema must fail, never initialize an empty healthy database.

Proposed monitor behavior:

| Signal | Interpretation / proposed local handling |
| --- | --- |
| `clear` | No pending rows; oldest age remains null |
| `pending` | Pending rows younger than 24 hours; record count and age |
| `stale` | At least one pending row is 24 hours old or older; surface to processing owner |
| `unknown` / `invalid_clock` | Incomplete/invalid time evidence; never report healthy |
| CLI nonzero or absent scheduled observation | Monitoring failed; never report healthy |
| HTTP 200 with SB `read` | Reader available, independently of backlog |
| HTTP failure or SB `unconnected` | Reader unavailable; diagnose separately |

The 24-hour stale threshold and 15-minute cadence are **proposed policy**, not
an existing SLA or active configuration. Install the reviewed SQL in an
operator-owned operations directory, pin the verified SQLite executable,
resolve the company DB from trusted server config, and attach the timer there.
Persist only aggregate counts/timestamps/types in a private local observation.
No external notification, business-system write, automatic state transition,
credential copy to jm, or direct company DB access for jarvis-svc is proposed.
Activation and any actual backlog processing remain outside this PR.

## Verification and handoff

`tests/test_company_reader_drain.py` exercises the real company-store schema:
empty queue, mixed pending/terminal rows, repeated receipts, workspace join,
UTC offsets and the inclusive 24-hour boundary, missing/malformed/future
receipt times, invalid clock, missing DB, privacy and unchanged database bytes.
Existing `tests/test_company_memory_reader.py` continues to prove scoped
list-only reads, mutation refusal, privacy and real CLI/socket behavior.

Focused verification: **32 passed**, lint clean, and language-server diagnostics
clean for the new test. No existing test was changed or weakened.

An initial shared-venv invocation failed collection because its editable
install imported test helpers from a different checkout. A lane-owned frozen
environment resolved that execution issue; it was not a reader regression.

Only the aggregate query, its regression tests and this proposal are delivered.
No production configuration, data, schema or services were changed. The
configured GitHub Project management tool/registry is absent on this host.
Issue #30 was reused directly; GitHub requery confirmed it is already linked
to the **JM Development** Project with status **In Progress**. No duplicate
registration or status change of that broader implementation issue is needed.
