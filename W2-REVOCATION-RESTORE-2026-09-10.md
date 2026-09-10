# W2 철회 후 설정 복원

철회 집합을 `state_root/revoked-jarvis-signing-key-ids`에 합친다. `config.toml`만 되돌리면 예전 키가 살아나지 않는다. 실수 철회 복구는 새 키 추가이지 옛 키 파일 복원이 아니다.

검증: `tests/test_scoped_read_policy.py` — 복원 후 `MEMORY_SCOPED_CONFIG_INVALID`; `key:next`만 유효. `tests/test_mcp_scoped.py` v1 — 철회 기록 뒤 같은 claim `sb_read_page`는 error, `Alpha fixture` 없음. 관련 28 passed.

운영 키를 돌리거나 journal을 고치지 않았다. M3 전체(백업 병합·열린 MCP 재바인딩 전 과정)는 아직이다.
