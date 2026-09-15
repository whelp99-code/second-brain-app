# 보류 분기 H1–H4 후보 b239c0b / 제품 83a7aba 독립 검토 (Claude)

2026-09-15T04:24:00.141466+00:00. 후보 `/var/tmp/sb-candidate-83a7aba/releases/8ea65a7d968fdcf99560f449b2a1ad656a99a2e9` wheel `6bc94e226c0158ab…`, source/wheel/installed 183 파일 일치. 원본 `/var/tmp/claude-night-e53dd66-GBr0la`.

**판정: 격리 인수(전체 회귀 결과 대기).** 보류였던 H1(M3 열린 연결·옛 설정 rollback), H2(보안 경계·symlink/FIFO/유실), H3(삭제 경합), H4(삭제 전 백업 수명)가 격리 fixture에서 구현·검증됨. 제품 변경은 `sb/postcompact_hook.py`의 stage 경로 보강뿐.

| 항목 | 직접 실행 |
|---|---|
| H1 tests/test_m3_open_connection_rollback.py | 3 passed (two stdio sessions deny after revoke; old config cannot revive revoked key; rollback compat allowed=false when store present) |
| H2 test_held_path_safety+test_postcompact_hook+test_revoked_keys | 53 passed (fifo/dir/symlink/dangling for stage file, stage dir, revocation store; regular file still writes) |
| H3 tests/test_delete_compile_race.py | 3 passed incl. real two-subprocess writer serialization then forget wins |
| H4 tests/test_pre_delete_backup_lifetime.py | 1 passed (post-forget backup restore stays empty after reindex) |
| tests/test_rollback_compat.py | 3 passed |
| ruff | All checks passed |
| basedpyright | 0 errors / 58 warnings in the repo venv (harness archive showed 2 'mcp' import errors = harness env only) |
| probes on 8ea65a7 candidate | inturn 17/17, quality 7/7, hangul 3/3 |
| full_regression | 1924 passed / 3 skipped / 670.32s / EXIT0 |

## 비고
- H4-scope: New H4 test covers a backup taken after forget. The pre-delete backup case (backup contains the record, delete, restore must not re-expose) is covered by existing tests/test_restore.py::test_restore_shifted_deleted_record_cannot_survive_signed_restore and the M12 DR harness (tombstone high-water, deleted_records=0 after restore); no new gap, but the directive wording asked for it explicitly - recorded as covered-elsewhere.
- ops: Ops SB current is still 2ccf0267 (8d1f8cc). If the full regression passes, promote b239c0b/83a7aba to the app root and relink (hook-only change; derived index schema unchanged so no generation rebuild expected).
