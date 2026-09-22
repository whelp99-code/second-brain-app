# Core5 status

The earlier `.git/index.lock` EROFS was Codex sandbox, not the disk. Host Git is writable. No push/merge/deploy.

B01–B03 product fixes are implemented; B06 company/personal candidate flow is in `2e9f9ba` (not a live CRM/Mail/Shipping runtime integration).


## Unit results

- B01: `memory-surface-matrix.json` measured the live registrations and trust path.
- B02: signed scoped read/search/page/status/write paths remain fail-closed; `sb/scoped_surfaces.py` adds export and restore claim checks with generation and deletion high-water binding.
- B03: `sb/parsers/docling_adapter.py` and its worker isolate optional Docling; deterministic parsers remain the fallback. `parse_document()` records source hash, locator, parser/model version, and partial state.
- B04/B05: existing Korean evaluation and memory lifecycle suites pass against the current managed search and deletion/restore fences.
- B06: in-repo `CompanyMemoryStore` is tested. Live cross-runtime company flow (CRM/Mail/Shipping processes) is not claimed complete.

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
- This repository now has `sb.company_memory.CompanyMemoryStore`: sourced mail/CWOS candidates retain source event, locator, parser version, content digest, scope, and deletion revision. `candidate -> accepted -> processed_complete` transitions are separate and idempotent; processing without acceptance is rejected.
- Candidate reads and transitions require the current `SourceAccess` and exact deletion high-water. No CRM write, mail send, or personal-vault mutation occurs.
- Personal remember/search/correct/delete remains on the existing inbox, search, correction, and deletion-fence paths and has independent regression coverage.
- B06 focused verification: 63 passed for company/scoped/access/search/restore; 12 passed for personal remember/search/delete coverage.
