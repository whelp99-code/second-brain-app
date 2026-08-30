# Second Brain Joint Implementation Assignment

You are the primary implementer in the isolated Orca worktree `/home/jm/orca/workspaces/second-brain-app/jarvis-terminal-memory-runtime`.

Read and obey:
- `AGENTS.md`
- `ORCA-JARVIS-SECOND-BRAIN-JOINT-DEVELOPMENT-PLAN.md`

Current baseline:
- This worktree starts from production-ready Second Brain `1.0.0` at `838bd18`.
- `uv run ruff check .`, `uv run basedpyright`, and `uv run pytest -q` pass with 364 passed / 3 skipped when the `embeddings` extra is installed.
- JARVIS is developed separately in `/home/jm/orca/workspaces/Orca-JARVIS/jarvis-terminal-memory-runtime`; do not edit it here.

Goal:
Complete the Second Brain provider side of the joint plan:
1. freeze/export the actual six-tool MCP contract (`sb_search`, `sb_read_page`, `sb_recent_changes`, `sb_open_conflicts`, `sb_remember`, `sb_run`) with typed health/no-data/error forms;
2. add `TerminalWorkSummaryV1` and versioned, idempotent write-request contracts for `remember|correct|forget|export` carrying candidate ID, closeout ID, receipt digest, purpose, sensitivity, retention, expected prior digest, and idempotency key;
3. add collision-safe request inbox persistence and MCP tools for JARVIS-approved write requests, status/reconciliation, and bounded artifact observation;
4. keep explicit user quick-capture (`sb_remember`/`sb_run`) distinct from JARVIS provenance;
5. implement correction, supersession, forgetting/tombstone propagation, bounded export, and restoration-safe deletion semantics across page/search/vector/daily/cache/export surfaces;
6. add terminal-work-summary compilation with citations and conflict behavior; never ingest live/raw terminal output as durable authority;
7. add doctor/status/capability fields needed by JARVIS contract drift and outbox reconciliation;
8. add systemd/runtime packaging needed for the new provider interfaces;
9. add full deterministic, adversarial, idempotency, crash/retry, conflict, deletion, restore, and MCP tests;
10. preserve the native Mac app's existing capture/search/file-sync/briefing behavior and the existing six tools.

Architecture/security boundaries:
- Second Brain has no ORCA worker/control authority.
- JARVIS never receives direct vault/database access.
- Only verified/approved write requests become durable operational summaries.
- Memory content cannot mint or change approval scope.
- No secrets, keystrokes, password prompts, private reasoning, arbitrary paths, raw terminal streams, or unrestricted exports.
- Interrupted writes must be reconcilable and idempotent; never silently replay an uncertain mutation.
- Do not commit, push, merge, or activate production. Leave a fully verified working diff.

Implementation rules:
- TDD, small modules, stable error codes, canonical JSON/digests.
- Keep backward compatibility with existing CLI/web/native app/MCP behavior.
- Run focused tests after each slice, then full ruff, basedpyright, pytest, package build, MCP smoke, and desktop API regression.
- Produce `.omo/evidence/joint-second-brain-completion.json` and `.omo/evidence/joint-second-brain-completion.md` with exact files/tests/remaining blockers. Do not claim completion while any provider-side requirement remains.

Begin with contract/schema tests, then implement in dependency order through full provider verification.
