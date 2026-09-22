# Core5 status

The earlier `.git/index.lock` EROFS was Codex sandbox, not the disk. Host Git is writable. No push/merge/deploy.

B01 measurement completed; B02 and B03 product fixes are implemented; B06 remains externally blocked.


## Unit results

- B01: `memory-surface-matrix.json` measured the live registrations and trust path.
- B02: signed scoped read/search/page/status/write paths remain fail-closed; `sb/scoped_surfaces.py` adds export and restore claim checks with generation and deletion high-water binding.
- B03: `sb/parsers/docling_adapter.py` and its worker isolate optional Docling; deterministic parsers remain the fallback. `parse_document()` records source hash, locator, parser/model version, and partial state.
- B04/B05: existing Korean evaluation and memory lifecycle suites pass against the current managed search and deletion/restore fences.
- B06 blocker: CRM C04, Mail M03, and Shipping H04 are outside this checkout and are not available as callable dependencies. The personal memory lifecycle remains independently testable; company-flow integration is not claimed complete.

## Host remasure 2026-09-22

`.venv312/bin/pytest -q tests/test_access_claims.py tests/test_mcp_scoped.py tests/test_scoped_status_mcp.py tests/test_scoped_write_mcp.py tests/test_restore.py tests/test_parsers.py tests/test_korean_search_evaluation.py tests/test_scoped_search.py tests/test_memory_access.py --maxfail=8`
rc=0; 114 passed, 6 warnings in 47.98s.

## Verification

- Passed: `.venv312/bin/pytest -q tests/test_access_claims.py tests/test_mcp_scoped.py tests/test_scoped_status_mcp.py tests/test_scoped_write_mcp.py`
- Passed: `.venv312/bin/pytest -q tests/test_restore.py tests/test_restore_access.py tests/test_parsers.py tests/test_connectors_inbox.py tests/test_uploads.py`
- Passed: `.venv312/bin/pytest -q tests/test_korean_search_evaluation.py tests/test_scoped_search.py tests/test_memory_access.py tests/integration/test_memory_lifecycle.py`
- Full suite has an environment-dependent MCP subprocess timeout in `tests/integration/test_generation_concurrency.py`; focused product suites above pass.
