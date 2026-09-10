# W3.1 전체 회귀

소스 HEAD `859691d`. 운영 전환 없음.

1. 관련 회귀 67 passed (`test_compiled_marker_recovery`, `test_vault`, `test_scoped_read_policy`, `test_mcp_scoped`, `test_access_claims`, `test_activated_orphan_rows`).
2. 첫 전체 실행: 4 failed / 1828 passed / 3 skipped (512s). 실패는 `test_memory_restore_reingress` — 철회가 남은 채 stdio 서버가 기동하지 않음.
3. `tests/restore_scoped_mcp.py`를 새 프로세스가 `MEMORY_SCOPED_CONFIG_INVALID`로 끝나도록 고침. restore 7 passed.
4. 두 번째 전체 실행: **1832 passed, 3 skipped, 532.49s, EXIT 0**. 로그 `/var/tmp/w3-full-pytest-2.log`.

후보 wheel은 아직 안 만들었다. W3.2.
