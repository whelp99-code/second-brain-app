# JARVIS F2 지시 — gjc-dispatch-assemble 4개 실패 해소 (2026-09-15)

작성: Claude Fable 5.1 (검증 역할). 구현: 기존 Grok. 리포: `/home/jm/orca/projects/Orca-JARVIS` (HEAD 4d76572, main, 미푸시). AGENTS.md 규칙 준수(실측 수치만 보고).

## 현상 (독립 재현)
`npx vitest run tests/unit/assembled-session-transport.test.ts tests/integration/gjc-dispatch-assemble.test.ts tests/integration/memory-postcompact.test.ts`
- 4d76572 작업 트리: 40 passed / 4 failed. 64715ba archive: 36 passed / **같은 4 failed** → 64715ba `fix: keep record_digest as version and join occurrence ids`부터 존재. N1 탓 아님.
- 실패 4건(`tests/integration/gjc-dispatch-assemble.test.ts` "gjc.dispatch assemble envelope"): binds each selected record to its own memory_ref / binds distinct records that share body and source to different evidence / keeps same-source different-body records on separate lineages / persists the same selected memories that the transport sends.
- 단언: `request.memories.map(m => m.memory_ref).sort()` 가 `["12345678","87654321"]`(fixture의 8-hex) 이길 기대하나 실제는 `sbrecord:v1:…` 값. `src/context-assembler.ts:147,166–180`은 `memory_ref`를 그대로 전달하고 `evidence_id`는 `digest+memory_ref`로 만든다.

## 판단 기준 (먼저 결정 후 수정)
1. **계약이 맞고 테스트가 낡은 경우**: 64715ba 이후 provider record 식별자는 `sbrecord:v1:<digest>`(SB `memory_records.record_id`)가 정본이고, dispatch envelope의 `memory_ref`도 그 값을 써야 한다면 → 테스트 fixture/기대값을 `sbrecord:v1:` 형식으로 갱신. 단, 각 테스트의 원 의도(record별 고유 memory_ref, 같은 본문·출처의 서로 다른 record는 다른 evidence, 같은 출처·다른 본문은 별 lineage, persisted == transport sent)는 그대로 검증되어야 한다.
2. **테스트가 맞고 회귀인 경우**: 8-hex `memory_ref`가 외부 계약(SB dispatch/persisted evidence, `contracts/` JSON schema)이라면 → 64715ba가 `memory_ref`를 record_digest로 덮어쓴 부분을 되돌리되 `version`은 record_digest로 유지.
근거는 `contracts/second-brain-*.json`의 memory_ref 정의, SB 측 `sb/memory_records.py`의 record_id 형식, 그리고 `CODEX-NIGHT-REVIEW-069aeaa.md`(64715ba consumer/dispatch 검증 범위)를 대조해 한 문단으로 기록한다. 어느 쪽이든 SB 제품(8d1f8cc)은 변경하지 않는다.

## 완료조건
- 위 3개 테스트 파일 **44 passed / 0 failed** (직접 실행 수치), `npm run typecheck` 백엔드 0 errors, `npm run lint` 통과 여부 그대로 보고.
- 선별 커밋 1개(테스트 또는 소스, 결정 근거를 커밋 본문에). **push 없음**. 운영 authority current(a3cbbbe) 미변경.
- `GROK-FINAL-VERIFICATION-REQUEST-2026-09-14.md` §3b F2를 "해소(커밋 <sha>, 결정: 계약/테스트 중 무엇)"로 갱신하고 IMPLEMENTATION-STATUS C행 F2 잔여 문구 제거. 격리 N1 dist 재빌드 여부: 소스가 바뀐 경우에만 `/var/tmp/jarvis-artifact-n1-<date>`로 새로 만들고 경로를 적는다(테스트만 바뀌면 dist 불변).
- 끝나면 이 세션이 vitest·typecheck를 독립 재실행해 검증한다. 추가 답변 대기 없음.
