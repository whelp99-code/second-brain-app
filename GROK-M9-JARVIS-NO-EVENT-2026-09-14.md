# M9 JARVIS compaction 이벤트 없음 — 고정

소스: `Orca-JARVIS/src/cli-gjc-commands.ts` 355–357.

JARVIS는 model-session context-compaction 이벤트가 없다. 삭제/정정 compaction은 이 트리거가 아니다.

- Claude Code `SessionStart(source=compact)` 훅은 **SB 클라이언트 경로**. JARVIS M9를 닫지 않는다. 재구현 금지 (`9d2041f` 한정 인수).
- `gjc.dispatch` assemble은 `model_transport` 필수 (`MEMORY_MODEL_TRANSPORT_REQUIRED`). 기본 Recording으로 성공을 가장하지 않는다.
- `memory postcompact`는 설정된 consumer command만. 허구 세션 이벤트 없음.
- native `/compact`는 `/var/tmp/sb-native-probe-8d1f8cc` 절차. 사용자 실행. `blocked_external`.

회귀: `tests/integration/gjc-dispatch-assemble.test.ts` “does not assemble when model_transport is missing”.
