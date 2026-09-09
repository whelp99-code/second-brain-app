# 삭제 차단 기록 이후 지식 상태 저장 실패 복구

기준 e5342b5. 실제 부분 forget 요청에서 새 상태 저장을 일시적으로 실패시켜 결함을 재현하고 수정했다.

## 재현된 문제와 수정

ErasureEngine이 삭제 차단 정보를 기록한 다음 BoundKnowledge 저장이 실패하면, 기존 RequestExecutor는 아직 pointer가 바뀌지 않았다는 이유로 요청을 failed로 종료하고 처리 파일을 제거했다. 실제 네 failure 조합에서 현재 세대는 원본 그대로, tombstone sequence는 증가, 다음 apply_once는 idle이었다. 기존 8개 확장 시나리오로 이 상태를 관측했다. 삭제 작업이 미완료인데 재처리할 요청이 없어진 것이 문제다.

새 EffectKnowledgeRebindError는 effect 성공 이후 재결합 구간 실패를 구분한다. RequestExecutor는 이 오류에서 요청을 terminal 처리하지 않고 reconciling으로 반환한다. 기존 lease/요청 파일을 보존해 만료 후 정상 claim·재실행 경로를 사용한다. effect 실행 전 실패와 다른 기존 terminal 오류의 처리는 유지한다. 새 재결합 exception은 원래 원인을 cause로 보존하며, 외부 반환 코드는 EFFECT_KNOWLEDGE_REBIND_FAILED다.

## 검증

실제 부분 삭제 lexical/hybrid×외부 철회 조합 각각에서 정상/실패복구를 실행했다. 실패 시 활성 세대가 바뀌지 않고 reconciling 반환, 일시적 오류 해소 후 executor를 닫고 새 객체로 원장을 다시 연 뒤 lease 만료 시각으로 재실행한다. proved 완료·남은 사실 검색·철회 우선·출처 검증과 tombstone sequence/set root 불변을 확인했다. 가짜 시각 진행으로 테스트하며 sleep은 없다.

`TMPDIR=/var/tmp uv run pytest -q tests/integration/test_bound_partial_forget.py tests/test_effect_knowledge.py tests/integration/test_memory_crash_recovery.py tests/test_request_executor.py --tb=short`: **22 passed / 21.50초**. Ruff 전체·diff 통과, effect_knowledge 타입 0오류/0경고.

## 범위와 한계

실제 DB·요청 처리·복구 객체 재생성 테스트이며 별도 OS 프로세스 SIGKILL 검증은 아니다. injection은 상태 저장 RuntimeError이고 영구 디스크 고장이나 전원 손실을 모사하지 않는다. 영구 충돌/저장 오류는 원인 해소 전 계속 복구 대기로 남을 수 있다. 이를 완료나 승인 예외로 덮지 않는다.

erasure 내부의 다른 위치에서 실패하는 경우, correction replay/취소 조합, SIGKILL, 복원 상태·scoped 접근·최신 설치본과 실제 업무·운영 및 M1–M14는 남는다. 전체 suite는 이번 제품 변경 후 다시 실행하지 않았다. 운영 DB·서비스·공용 registry 변경과 push 없음.
