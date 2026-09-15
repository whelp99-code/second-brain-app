# 보류 분기 재개 지시 — 2026-09-15

작성: Claude Fable 5.1(검증 역할). 구현: 기존 Grok. 사용자 승인: 2026-09-15 "모두 승인하고, 너에게 실행을 위임한다." 이 지시로 `blocked_deferred`였던 아래 분기의 **실행·구현·검증을 재개**한다. 운영 전환은 이 세션이 별도로 수행하므로 Grok는 SB 제품 소스·테스트·격리 검증만 맡는다. push·auth 복사·실사용자 삭제 없음. 운영 데이터(`~/.local/share/second-brain`, `~/.local/state/second-brain`)는 읽지도 쓰지도 않는다. 모든 검증은 `TMPDIR=/var/tmp` 격리 fixture.

기준 핀: SB HEAD `c7b34a8`(제품 `8d1f8cc`, 운영 current `2ccf0267`), JARVIS `8745ce7`. 원 요구: `CURSOR-HANDOFF-2026-09-10.md` §7 M3/M5/M11/M13, `GROK-INTEGRATED-COMPLETION-HANDOFF-2026-09-11.md` B/E. 참고 증거(옛 바이트, 승계 금지): `/var/tmp/codex-night-01cedbb-ngqqvboh/{race.py,race.json,record-overlap.*,test_forget_scoped.py,test_record_overlap.py}`, `CODEX-NIGHT-REVIEW-01cedbb.md` §"제한 전 record-overlap"(held_read 실패 문구 정정).

## 분기별 완료조건 (각각 정상/실패/복구를 함께)

### H1. M3 열린 연결·과거 설정/백업 rollback 수명
- 철회 후에도 **열려 있던 scoped MCP 연결**(stdio 프로세스 2개 이상)이 다음 요청에서 거부되는지(`MEMORY_ACCESS_SCOPE_UNAVAILABLE` 또는 동등), 정책 revision 복구 후 새 claim만 통과하는지.
- 과거 `config.toml`/백업 archive를 `sb restore --to <격리>`로 복원한 뒤 **옛 서명키 claim이 거부**되고(`revoked-jarvis-signing-key-ids` 지속), 새 키는 유효한지. `deploy/check-rollback-compat.py`의 `allowed=false` 경로도 fixture로 1회.
- 테스트: `tests/test_revoked_keys.py` 확장 또는 새 파일. 실패/복구 분기 포함.

### H2. 보안 경계·symlink/FIFO (M5/B/E)
- 철회 marker·stage·inbox·restore 대상 경로에 **기존 symlink / dangling symlink / 디렉터리 / FIFO / 유실 / 초기화 중단**이 있을 때 안전 실패(명시 코드, 원본 보존, 운영 root 이탈 0). `O_NOFOLLOW`/`dir_fd`/exclusive create 규칙이 이미 있으면 재증명, 빠진 곳(예: `sb/postcompact_hook.py` stage 파일 `_stage_path` write_text, `sb/revoked_keys.py`, restore dest)은 수정.
- 테스트: 경로별 parametrize. 정상 경로 회귀 무변경.

### H3. 삭제 경합 (M13/M11)
- 같은 page/record에 대해 **삭제(forget)와 정정/게시가 동시에** 일어날 때: 삭제가 승리하면 재노출 0(재색인·복원·재유입 포함), 게시가 승리하면 tombstone high-water가 이후 삭제를 정확히 덮는지. pinned-read 중 publish는 `GENERATION_WRITER_BUSY`(이미 4eff746)이므로 그 이후 순서만.
- 실제 두 프로세스(subprocess) 경합 1회 + 결정적 단위 테스트. 옛 `race.py` 재사용 가능하나 현재 바이트로 다시 작성.

### H4. 삭제 전 백업 수명 (M12/M13)
- 삭제 직전 백업 archive에 대상이 남아 있어도 **복원 후 tombstone high-water 승계로 재노출 0**, 백업 검증(`sb backup`/verify)이 tombstone 시퀀스를 기록하는지, 오래된 백업 복원 시 `E_RESTORE_FAILED`/fence 요구가 나는지.
- 테스트: 격리 backup→forget→restore→search 0 시나리오.

## 진행 규칙
- 분기마다 별 커밋(테스트+필요한 최소 제품 수정). 각 커밋 메시지에 재현 명령과 직접 실행 수치.
- 변경 파일 Ruff 0, basedpyright 0 errors. 관련 테스트만 실행하고 마지막에 전체 회귀 1회(`pytest tests`) 수치 보고.
- 제품이 바뀌면 `prepare-release.py /var/tmp/sb-candidate-<short>`로 격리 후보를 만들고 `GROK-INTEGRATED-CANDIDATE-HANDOFF-2026-09-13.md`에 핀·wheel·수치를 적어 이 세션에 인계한다(이 세션이 독립 검증 후 필요 시 운영 재전환). 제품이 안 바뀌면 후보 없음.
- 콘텐츠 제한 안내가 다시 뜨면 그 분기만 `held(reason)`으로 표시하고 나머지를 계속한다. 추측 우회 금지.
- 추가 답변 대기 없음. H1→H2→H3→H4 순.
