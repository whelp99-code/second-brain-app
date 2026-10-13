# Company backlog monitor

Task: `TASK-SB-BACKLOG-MONITOR-20261013`. Refs #30 and merged audit PR #65.
Target host: `jm-omachy`. The wrapper and user units are runnable artifacts;
this PR does **not** install, enable or start them in production.

## Files and schedule

- `deploy/company-backlog-monitor.py`: standalone Python 3.12+ stdlib wrapper.
- `deploy/company-reader-drain.sql`: existing, unchanged aggregate query.
- `deploy/second-brain-company-backlog.service`: user oneshot, isolated Python
  (`/usr/bin/python3 -I`), 60-second timeout and no Internet address families.
- `deploy/second-brain-company-backlog.timer`: every 15 minutes
  (`*-*-* *:00/15:00`), up to one minute scheduling accuracy, persistent across
  downtime. Missed calendar runs are caught up when the timer next activates;
  they are not a historical backlog reconstruction.

The same named oneshot service is not run concurrently by its timer. Use that
service for manual checks rather than starting multiple independent writers.
The wrapper has no watcher, queue, HTTP endpoint, account/key handling, external
notification, Notion write or candidate state-transition code.

## Result consumed by the morning report

The fixed jm-user result path is:

```text
/home/jm/.local/state/second-brain/company-backlog-monitor/latest.json
```

Equivalent: `~/.local/state/second-brain/company-backlog-monitor/latest.json`.
The default user state base on this host is `~/.local/state`; if an operator
changes the user manager's `XDG_STATE_HOME`, align `StateDirectory` and the
fixed output path before activation rather than silently moving the morning
report's input.

Each observation replaces this file atomically with **one JSON line**, mode
`0600`, in a private result directory. Once replacement succeeds, stdout is
identical to the published line, even if later directory durability confirmation
fails. The user service journal retains the observation and any separate error:

```bash
journalctl --user -u second-brain-company-backlog.service
```

No customer names, source text, IDs, amounts, credentials, input paths or raw
exception messages are written to JSON or wrapper logs. Only aggregate
counts/timestamps/status, fixed error codes and the no-drain flag are emitted.

| JSON field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `observed_at` | UTC ISO-8601 observation time |
| `status` | `CLEAR`, `PENDING`, `STALE`, `UNKNOWN` or `ERROR` |
| `pending_count` | Candidate + accepted-but-unprocessed rows; null on error |
| `pending_received_last_24h` | Pending rows first received in the last 24 hours |
| `oldest_pending_received_at` | Oldest valid first receive receipt; null if absent |
| `oldest_pending_age_seconds` | Age of that receipt; null for empty/unknown/error |
| `pending_age_unknown_count` | Pending rows without a usable first receive time |
| `invalid_receipt_time_count` | Invalid or future receipt timestamps |
| `threshold_seconds` | `86400` (24 hours, inclusive boundary) |
| `error_code` | null, or a fixed machine-readable failure code |
| `drain_authorized` | Always `false` |

`STALE` means at least one known pending age is **at least 86400 seconds**.
A known stale candidate still yields `STALE` if another row has unknown age;
the unknown/invalid counters remain visible. With no known threshold violation,
incomplete time provenance yields `UNKNOWN`, not a healthy zero. `CLEAR` means
the aggregate query found no pending rows and no invalid time evidence.
`PENDING` means pending rows with valid ages below the threshold.

Morning-report consumer rules:

1. Read and parse the single JSON object from the path above. Require schema 1
   and a valid timezone-aware `observed_at`. Missing, malformed or unsupported
   data means **monitor unverified**, not zero backlog.
2. Require observation age between zero and **30 minutes**. An older file or
   future timestamp means **monitor unverified**. Do not use mtime instead of
   the observation timestamp or present an old count as current.
3. For fresh `STALE`, report pending count and oldest age; retain any unknown
   timestamp warning. `UNKNOWN`/`ERROR` must remain explicit. Never convert null
   measurements into zero or call them a drained queue.
4. Failure **before replacement** leaves the previous complete file, if any.
   Failure **after replacement** leaves the new observation and identical stdout,
   but emits `RESULT_DURABILITY_UNCONFIRMED` on stderr and exits 1. Observation
   status is not a durability guarantee. Check the service's failure result or a
   newer journal error before treating a snapshot as a successfully finalized run.
   An absent scheduled
   update beyond 30 minutes is unverified even if the last status was `CLEAR`.

This documents the input contract for omonyang's morning report; it does not
modify that reporter or send a notification. Reader HTTP availability and
backlog processing are different signals: no read or snapshot drains a queue.

## Failure behavior and safety

The wrapper opens SQLite with `mode=ro` and `PRAGMA query_only=ON`, running the
existing SQL in one read transaction. It never creates an absent company DB
or changes candidates/receipts. Query/schema/file-read failures publish a fresh
`ERROR` with null measurements and `DATABASE_READ_FAILED`, then return exit 1.
`STALE` and `UNKNOWN` are successfully measured states and return exit 0.

Results must be outside the source database directory so a mistaken output
cannot replace the database or its sidecars/source files. Such a conflict emits
`OUTPUT_PATH_CONFLICT` and exit 1 without writing that destination. Pre-replacement
failure emits `RESULT_PUBLISH_FAILED` and exit 1; inability to resolve safe input
and output paths emits `PATH_RESOLUTION_FAILED` without writing an unchecked
destination. Neither substitutes a
success result. Temporary output is written/fsynced next to the target and
renamed, so readers see an old complete or new complete JSON file, not a partial
one. The temporary file is removed if publication fails before replacement.

`os.replace` is the visibility commit point. Directory open/fsync/close failures
after it do not undo publication: the wrapper keeps the published JSON as stdout,
emits only the fixed `RESULT_DURABILITY_UNCONFIRMED` code on stderr and exits 1.
The JSON still describes the measured backlog; it does not claim a successful
durability check. The error is not hidden or converted into exit 0. No compensating
rewrite is attempted on storage that just failed, and the consumed temporary name
is not cleaned up again. This preserves file/stdout agreement without claiming
crash durability or rollback after a committed replacement.

The service uses a fixed DB path:
`~/.local/share/second-brain-company/mail-ms/company.db`.
The wrapper takes only operator-controlled `--database` and `--output` paths;
there is no caller-controlled SQL, remote fetch or credential config. Confirm
the DB location against trusted local registration before installation.
The service's `StateDirectory` creates its private result directory and grants
the write exception while the rest of home/system is read-only.

## Operator activation after Cursor review (not executed by this PR)

Install the reviewed wrapper and SQL together; the wrapper locates the SQL
relative to its own installed file. Do not point the service at a mutable
development checkout or change the existing company reader/broker services.

```bash
umask 077
install -d -m 0700 "$HOME/.local/lib/second-brain-monitor"
install -m 0600 deploy/company-backlog-monitor.py deploy/company-reader-drain.sql \
  "$HOME/.local/lib/second-brain-monitor/"
mkdir -p "$HOME/.config/systemd/user"
install -m 0644 deploy/second-brain-company-backlog.service \
  deploy/second-brain-company-backlog.timer "$HOME/.config/systemd/user/"
systemd-analyze --user verify \
  "$HOME/.config/systemd/user/second-brain-company-backlog.service" \
  "$HOME/.config/systemd/user/second-brain-company-backlog.timer"
systemctl --user daemon-reload
systemctl --user start second-brain-company-backlog.service
systemctl --user enable --now second-brain-company-backlog.timer
systemctl --user list-timers second-brain-company-backlog.timer
```

Check the first result and journal before consuming it in a morning report.
This timer belongs to jm's user manager: it runs while that manager runs.
Unattended boot execution depends on the host's existing user-manager/linger
policy; this PR does not change that policy or claim a deployed boot check.
If sandbox/user-namespace support or the fixed paths are unsuitable, leave the
unit inactive and reconcile the operator configuration after review.

To stop only the monitor after separate operator authorization:

```bash
systemctl --user disable --now second-brain-company-backlog.timer
systemctl --user stop second-brain-company-backlog.service
```

Preserve the last report as historical evidence and treat it as unverified once
it ages out. These commands do not drain or acknowledge company candidates.

## Verification

Focused tests use fixed observation times and real fixture databases, covering
empty/recent/exact-threshold/stale/unknown/error states, source immutability,
one-line JSON and stdout equality, file permissions, atomic replacement and
rename/read failures. Unit tests inspect machine-consumed service/timer fields,
not prose.

```bash
uv run --frozen python -m pytest -q \
  tests/test_company_backlog_monitor.py tests/test_company_reader_drain.py
uv run --frozen ruff check \
  deploy/company-backlog-monitor.py tests/test_company_backlog_monitor.py
uv run --frozen basedpyright \
  deploy/company-backlog-monitor.py tests/test_company_backlog_monitor.py
systemd-analyze --user verify \
  deploy/second-brain-company-backlog.service deploy/second-brain-company-backlog.timer
systemd-analyze --user calendar '*-*-* *:00/15:00'
```

Standalone inspection, with a result directory separate from the company DB:

```bash
/usr/bin/python3 -I deploy/company-backlog-monitor.py \
  --database "$HOME/.local/share/second-brain-company/mail-ms/company.db" \
  --output /tmp/sb-backlog-inspection/latest.json
```

Unit verification and a one-shot wrapper run prove the artifacts, not a running
production timer. Installation, enablement and scheduled production observations
remain operator-owned after review.

### Captured pre-deployment evidence

On `jm-omachy`, focused wrapper/SQL tests: **25 passed**; Ruff clean;
basedpyright **0 errors, 0 warnings, 0 notes**. `systemd-analyze --user verify`
on both templates and calendar parsing returned exit 0.

The actual wrapper read the company DB at **2026-10-13T04:33:52.920Z** and
published to a task-owned QA directory, not the operational result location:

```json
{"status":"STALE","pending_count":21,"pending_received_last_24h":20,"oldest_pending_received_at":"2026-10-09T12:03:24.451Z","oldest_pending_age_seconds":318628.469,"pending_age_unknown_count":0,"invalid_receipt_time_count":0}
```

The full artifact was one JSON line matching stdout, with no source payloads.
The earlier read-only run also confirmed unchanged DB bytes. A real CLI call
with an absent fixture DB returned exit 1 and an identical file/stdout
`ERROR`/`DATABASE_READ_FAILED` record with null measurements, without creating
the DB. Test/result directories were removed after capturing this evidence.
No user unit was installed, enabled or started by these checks.
