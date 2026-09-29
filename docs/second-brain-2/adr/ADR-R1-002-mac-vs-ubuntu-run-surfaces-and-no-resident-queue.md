# ADR-R1-002 — Mac vs Ubuntu run surfaces, and no resident queue

Status: accepted for R1. Date: 2026-09-28.
Device and production-scheduler acceptance stay NOT_RUN.

## Context

The same repo contains an Ubuntu server package and a Mac client. AGENTS.md names Ubuntu `/home/jm/orca/projects/second-brain-app` as the selected app root and `/Volumes/DevSpace/second-brain-app` as a historical Mac path that must be verified before use. The vault `/Volumes/DevSpace/second-brain` is a different repo. This lane did not verify either Mac path on a machine.

P00 asks for an explicit split between those run surfaces, the admission ledger, and the forbidden resident queue.

## Decision

### Ubuntu server (this checkout)

- Run surface is a CLI, not a daemon queue. `sb run` is oneshot work (ingest, compile, briefing) under the pipeline lock. Unit template `deploy/systemd/second-brain.service` is `Type=oneshot` with `ExecStart=/usr/bin/env sb run`. `second-brain.timer` is `OnCalendar=hourly` with `Persistent=true`. That timer is an operating-system scheduler, not an in-process queue. Registering it on a live host is P07-1 and was not done.
- Backup is a separate oneshot. `second-brain-backup.timer` is daily `03:15` plus randomized delay. Not executed here.
- Loopback HTTP is `sb web --host 127.0.0.1 --port 8765`. Unit template `second-brain-web.service` is `Type=simple` with `Restart=on-failure`. That process serves requests. It is not a resident ingest queue, event bus, or file watcher. R1 adds no `threading.Thread`, `asyncio.create_task`, inotify, watchdog, or `sched` usage under `sb/` outside the existing web/mcp exceptions (coupling scan 2026-09-28: no matches).
- Source databases stay read-only. `unified-db` asserts both read-only settings before SELECT. Reconciliation progress, when present, is encoded in the adapter cursor. There is no `sb reconcile-sources` command in R1.
- Admission of personal observations is a file journal `<vault>/.sb/observations/`, written on the request path and advanced by the normal pipeline. Unknown is not searchable. No new server thread waits on that journal.
- MCP is an explicit `sb mcp` / `sb_run` surface. It does not share mutable pipeline state. `personal-memory-v1` is not in this tree yet (L4.A). Existing profile sidecars are unchanged versus `bdaa363`.

### Mac client

- `clients/macos` is Swift. It may watch user-selected local folders and upload through the bounded desktop API. The server still ingests only from `inbox/`. Folder-sync receipt durability on a real Mac is GATED-DEVICE (P16-17). This host cannot compile Swift; `tests/test_macos_client_contract.py` is string-level only.
- The client talks to loopback `127.0.0.1:8765`, documented as reached through an SSH tunnel on `127.0.0.1:18765` (`clients/macos/SecondBrainMac/AGENTS.md`). That tunnel was not opened here.
- Phone History on iPhone is a separate app. Server sink code can post to the upload boundary; a physical device run is NOT_RUN (P00-4).

### Payload vs delivery

Generating a notification payload, receiving HTTP 2xx (`transport_accepted`), and a human opening the notification are three states. 2xx is not a device receipt. Provider integration and opened-signal acceptance are NOT_RUN (P07-2, P07-3).

### Paths that are not interchangeable

| Surface | Path or unit | Verified on 2026-09-28? |
| --- | --- | --- |
| Ubuntu checkout used for this baseline | `/home/jm/orca/projects/second-brain-app-wt/r1-l4b` | yes, git facts only |
| Selected app root named in AGENTS.md | `/home/jm/orca/projects/second-brain-app` | not used (another session owns it) |
| Historical Mac app root | `/Volumes/DevSpace/second-brain-app` | NOT_RUN |
| Mac vault | `/Volumes/DevSpace/second-brain` | NOT_RUN; different repo |
| Installed systemd units on Ubuntu prod | `deploy/systemd/*.service` templates exist in git | live registration NOT_RUN |

## Consequences

No R1 lane may add a resident queue, event bus, file watcher, or server thread. Mac folder watches stay in the client. Ubuntu scheduling stays in systemd timers calling oneshot `sb` commands, and those timers are not approval to cut over production. A green checkout pytest is not evidence that the Mac path, the tunnel, TLS, or an installed unit works.
