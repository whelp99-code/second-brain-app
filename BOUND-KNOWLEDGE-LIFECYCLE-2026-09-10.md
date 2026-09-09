# 본문 결합 상태의 정정·삭제·복원 검증

기준 제품 4c2c7c4. 제품 동작을 바꾸지 않고 실제 provider lifecycle 통합 검증을 확장했다.

## 실행 범위

기존 remember→correct→export→forget 요청 처리기를 lexical/hybrid 각각 실행한다. 추가 두 경우는 remember materializer가 만든 실제 페이지에 컴파일과 동일한 본문 digest 상태를 시험용으로 기록한 뒤 실제 봉인·publication을 진행한다. 이는 실제 compiler 재실행은 아니며, 상태 seed만 fixture이고 뒤의 계약·효과·세대·proof 검증은 기존 실제 경로다. 기존 무상태 두 경우도 유지한다.

- 최초 본문은 active 검색에서 VERIFIED로 조회된다. 외부 registry에도 동일 page ID의 오래된 승인 행을 남긴다.
- 실제 correct 요청 이후 이전 내용의 lexical 결과는 없고 semantic 결과에도 이전 본문이 없다. 새 본문은 reference에서 UNVERIFIED이고 active에서 제외된다. 따라서 오래된 내부 digest/외부 ID-only 승인이 새 본문으로 넘어가지 않는다.
- 실제 forget 요청 이후 해당 본문은 reference/active 모두에서 제외된다. 기존 provider inventory·absence/proof·export 검증은 그대로 유지했다.
- 실제 restore sanitizer에서 tombstoned 내용은 reference에 없으며, 정상 복원 문서는 reference에서 회수된다. 오래된 외부 ID 승인이 있어도 active로 승격되지 않는다. 복원 후보의 비활성 상태와 기존 활성 세대 불변 검증도 유지했다.

## 결과

`TMPDIR=/var/tmp uv run pytest -q tests/integration/test_memory_lifecycle.py tests/integration/test_memory_restore_reingress.py tests/test_generation_knowledge.py --tb=short`: **16 passed / 21.31초**. Ruff 전체·diff 통과.

첫 확장 실행 1건은 hybrid에서 이전 질문에 결과가 무조건 없어야 한다는 fixture 기대가 잘못됐다. 의미 검색은 새 정정 내용을 돌려줄 수 있고 시험 encoder는 동일 방향 벡터를 사용한다. lexical에는 이전 내용이 없고 semantic snippet에도 이전 본문이 없는지를 검증하도록 수정했다. 필터나 제품 검색 규칙을 완화하지 않았다.

## 완료되지 않은 기능

새 정정 본문과 정상 복원 문서에 자동 처리 상태를 명시적으로 기록하는 연결은 여전히 없다. 현재 UNKNOWN/UNVERIFIED는 과거 승인을 잘못 승계하지 않는 결과일 뿐 전체 기능 완료가 아니다. '재승인'은 반드시 사람이 승인해야 한다는 뜻이 아니며 새 사람 승인 gate를 추가하지 않는다. record 범위 효과를 page 전체 승인으로 확대하지 않는 내부 자동 상태 규칙이 필요하다.

실제 사용자 업무·다른 모델 공유·native 보존/삭제·최신 설치본과 운영·복구·M1–M14는 남는다. 운영 DB·서비스·공용 registry 변경이나 push 없음. 이번 테스트 수정 후 전체 suite를 재실행한 결과는 아니다.
