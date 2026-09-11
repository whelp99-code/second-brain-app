# Grok 재개 상태

시각: 2026-09-11. **status=running**

마지막: `pytest tests/test_rollback_compat.py` 2 passed. JARVIS `eeac005` `assembleModelRequest` 격리 프로브 delivered_excerpt=true, live 모델 없음.

인계 [GROK-INTEGRATED-COMPLETION-HANDOFF-2026-09-11.md](GROK-INTEGRATED-COMPLETION-HANDOFF-2026-09-11.md) 전체 A–F/M1–M14 유지. Grok이 구현·자체 검증, Codex는 최종 독립 검증. 운영 전환/인증 복사/원격 push 없음. W4 drain 차단은 전환만 막는다.

## 바로 할 일

1. `41f0751` 자동 rollback을 배포 코드·런북에서 거부하고 검증된 복구 대안을 적는다.
2. JARVIS 요청 조립 경계를 격리에서 본문·출처·버전·예산까지 재고, live 인증과 분리한다.
3. 코드가 바뀌면 같은 HEAD에서 새 wheel·JARVIS dist로 표준/`--work`/유지보수를 다시 돌린다.

## 아직 안 끝난 독립 작업

- 철회 정본 수명·복원 후 새 키 경로를 배포 계약으로 고정
- 격리 MCP 지연/재시도, DR 복원 후 새 쓰기, 브라우저 실패→복구
- 업무 계보/재전송 격리 수명
- 제출서의 옛 “artifact 없음”/이전 dist 경로 정정

## 진짜 외부 조건 (지금 요청하지 않음)

- drain 허가, 운영 중단 창
- native 클라이언트 인증 (복사 금지)
- 사용자 지정 검색 100–300문, 실사용자 종단 업무 ID
