# 상태 재결합 실패의 원장·publication 롤백

기준 224033d. effect_knowledge의 prior 행 순서를 page_id/content_digest로 명시해 여러 페이지의 처리 순서를 결정적으로 만들었다. 실패 원자성은 기존 transaction과 generation staging 처리를 재사용하며 새 승인 예외를 추가하지 않았다.

## 새 검증

1. 두 페이지 중 첫 결과 상태를 기록한 뒤 두 번째의 기존 REJECTED 상태와 충돌시키는 실제 SQLite 테스트. 두 페이지를 순서대로 시도했음을 관측하고, 첫 새 상태도 rollback됐으며 기존 prior 두 상태와 REJECTED 행은 보존됨을 재접속으로 확인했다.
2. 실제 GenerationMutationService에서 현재 승인 본문과 충돌할 새 본문을 fixture로 구성. staging에서 본문 수정 후 상태 충돌을 발생시킨다. ValueError 이후 활성 generation ID·원문 bytes·manifest 검증이 그대로 유지됨을 확인했다. 이어 다른 mutation이 잠금을 얻고 기존 본문을 유지해 writer가 막히지 않음을 확인했다.

두 번째는 effect의 파일 변경을 시험 callable로 재현한 publication 경계 검사다. 실제 RequestExecutor의 tombstone·reingress가 이미 변경된 뒤 실패하는 전체 복구를 검증한 것은 아니다. SIGKILL/전원 손실 테스트도 아니다. 별도 기존 통합 테스트로 실제 부분 forget과 correct/export/forget 성공 경로 회귀를 함께 실행했다.

## 결과

`TMPDIR=/var/tmp uv run pytest -q tests/test_effect_knowledge.py tests/integration/test_bound_partial_forget.py tests/integration/test_memory_lifecycle.py --tb=short`: **16 passed / 27.67초**. Ruff 전체·diff 통과, effect_knowledge 타입 0오류/0경고.

남은 인수는 tombstone/reingress 변경 이후 실제 executor 실패·재시도, SIGKILL 각 경계, 복원 상태, scoped 접근 분류, 실제 사용자 업무·다른 모델·최신 설치 쌍·운영 및 M1–M14다. 전체 suite는 이번 변경 후 다시 실행하지 않았다. 운영 DB·서비스·공용 registry 변경과 push 없음.
