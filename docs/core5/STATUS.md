# Core5 status

The earlier `.git/index.lock` EROFS was Codex sandbox, not the disk. Host Git is writable. No push/merge/deploy.

B01–B03 product fixes are implemented. B06 now has a package-owned `sb-company` composition surface in source; it is not deployed, and the CRM/Mail donor publisher remains a distinct pending integration.


## Unit results

- B01: `memory-surface-matrix.json` measured the live registrations and trust path.
- B02: signed scoped read/search/page/status/write paths remain fail-closed; `sb/scoped_surfaces.py` adds export and restore claim checks with generation and deletion high-water binding.
- B03: `sb/parsers/docling_adapter.py` and its worker isolate optional Docling; deterministic parsers remain the fallback. `parse_document()` records source hash, locator, parser/model version, and partial state.
- B04/B05: existing Korean evaluation and memory lifecycle suites pass against the current managed search and deletion/restore fences.
- B06: `CompanyMemoryStore` and the separate packaged `sb-company` CLI are tested with signed workspace authority and durable receipts. Live donor publication from CRM/Mail/Shipping and deployment are not claimed complete.

## Host remasure 2026-09-22

`.venv312/bin/pytest -q tests/test_access_claims.py tests/test_mcp_scoped.py tests/test_scoped_status_mcp.py tests/test_scoped_write_mcp.py tests/test_restore.py tests/test_parsers.py tests/test_korean_search_evaluation.py tests/test_scoped_search.py tests/test_memory_access.py --maxfail=8`
rc=0; 114 passed, 6 warnings in 47.98s.

## Verification

- Passed: `.venv312/bin/pytest -q tests/test_access_claims.py tests/test_mcp_scoped.py tests/test_scoped_status_mcp.py tests/test_scoped_write_mcp.py`
- Passed: `.venv312/bin/pytest -q tests/test_restore.py tests/test_restore_access.py tests/test_parsers.py tests/test_connectors_inbox.py tests/test_uploads.py`
- Passed: `.venv312/bin/pytest -q tests/test_korean_search_evaluation.py tests/test_scoped_search.py tests/test_memory_access.py tests/integration/test_memory_lifecycle.py`
- Full suite has an environment-dependent MCP subprocess timeout in `tests/integration/test_generation_concurrency.py`; focused product suites above pass.

## Host remasure 2026-09-22

- B04 raw RC: `0` — 43 passed (`tests/test_korean_search_evaluation.py`, `tests/test_scoped_search.py`, `tests/test_memory_access.py`).
- B05 restore raw RC: `0` — 17 passed (`tests/test_restore.py`, `tests/test_restore_access.py`).
- B05 lifecycle raw RC: `124` from a 45-second timeout (`tests/integration/test_memory_lifecycle.py`); no result was emitted before timeout. This is retained as an environment/test-process hang and is not reported as a pass.

## B06 company/personal separation

- Read-only donor inputs: CRM C04 `1b0122d` (migration 0023 and follow-up state) and Mail M03 `2ffe7aa` (`CwosWorkSystemAdapter` candidate-only boundary).
- `sb.company_memory.CompanyMemoryStore` now requires a canonical workspace UUID, keeps company records and receipts in a separately configured SQLite database, and exposes explicit `candidate -> accepted -> processed_complete` or `candidate -> rejected` transitions. Invalid transitions fail closed.
- New `sb-company` packaging metadata points to `sb.company_memory_cli:main`. Its company-only Ed25519 authority binds provider, workspace, principal, agent/session, project scope, policy, operation-specific purpose, request digest, expiry, current deletion high-water, and a trusted non-revoked key. Frozen personal profiles and the personal `sb` runtime are unchanged.
- Every authorized operation and its idempotent receipt commit atomically. A company DB equal to or below a configured personal-data root is refused; company code does not import the vault, inbox, pipeline, personal search, web, or MCP runtime.
- [Bounded design](COMPANY-MEMORY-PRODUCT-DESIGN.md) and [donor contract](COMPANY-MEMORY-DONOR-CONTRACT.md) define the installed boundary. Donor outbox publication/acknowledgement is pending and must not be inferred from CRM schema or Mail's read-only adapter.
- Current increment verification: 19 focused tests passed; an isolated wheel install invoked the generated `sb-company` executable in a separate process through receive/read/accept/process and denied wrong workspace, unsigned authority, and stale deletion fence while preserving a personal marker. This is source/package evidence, not deployment evidence.
- Personal remember/search/correct/delete remains on the existing inbox, search, correction, and deletion-fence paths and has independent regression coverage.
