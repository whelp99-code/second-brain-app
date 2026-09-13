# M9 세션 compaction — 공개 계약 (a48cd07 N1–N3)

공식 hooks: PostCompact는 decision control이 없고 additionalContext 소비가 문서화되어 있지 않다 (`CODEX-NIGHT-REVIEW-a48cd07` official-hooks-reference). UserPromptSubmit는 additionalContext를 모델 문맥에 주입한다 (Claude 2.1.261 훅 표).

## 연결

1. **PostCompact** (부수 효과): `sb postcompact-hook`이 재선택 결과를 `.sb/session-memory/<session>.json`에 적는다. stdout `{}`. additionalContext를 소비 성공으로 쓰지 않는다.
2. **UserPromptSubmit** (문서화된 다음 요청 주입): 같은 명령이 stage를 읽어 `hookSpecificOutput.additionalContext`를 낸다. 동일 event_digest 재전달은 `{}`. 새 compact_summary는 재선택.
3. **JARVIS 구성 transport**: `JARVIS_MODEL_TRANSPORT_PATH` → `FileModelTransport`. `jarvis memory postcompact`는 stdin 기본 읽기. 없으면 `MEMORY_REFERENCE_OPTIONS_REQUIRED` (로그인 부족이 아님). 동일 event_digest는 send하지 않음.

합성 검증: SB `tests/test_postcompact_hook.py` 10 passed. JARVIS `memory-postcompact.test.ts` 8 passed. 기존 dispatch 정상 3 passed. native 훅 등록/실모델 없음.

한계: UserPromptSubmit 공개 등록은 운영 settings에 쓰지 않음. 예시만 인계 문서.
