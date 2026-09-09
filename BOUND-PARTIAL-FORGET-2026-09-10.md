# 부분 삭제 후 남은 승인 기억 인수

기준 제품 ee02047. 새 tests/integration/test_bound_partial_forget.py에서 실제 RequestExecutor의 forget 요청을 사용한다.

## 시나리오

한 CAS 원본의 두 기록으로 페이지를 materialize하고, 실제 본문 해시에 ACTIVE/APPROVED 상태를 시험용으로 결합한 뒤 공통 mutation으로 봉인·publication한다. 이 초기 seed는 실제 모델 컴파일을 대신하는 fixture다. 이후 삭제는 target resolution·서명된 요청 접수·실제 executor·erasure·새 세대 publication과 proved 상태를 거친다.

두 기록 중 '삭제할 기록은 화요일 회의입니다'만 지운다. 남길 기록은 '남길 기록은 금요일 배포입니다'. lexical/hybrid 각각 외부 철회 유무를 조합해 네 경우를 실행했다.

- 삭제 대상은 lexical 결과와 semantic snippet에서 사라진다.
- 미철회 경우 남은 사실은 active 검색의 VERIFIED로 회수된다.
- 삭제 전 외부 registry에서 RETIRED/REVOKED 처리한 경우, 새 내부 본문 상태가 생겨도 active 결과는 없다. 남은 사실은 reference의 UNVERIFIED로 조회된다.
- 남은 페이지는 삭제된 원본을 가리키는 대신 memory-effect 출처로 다시 결합되며 audit_citations를 통과한다.
- 외부 registry가 원래 없었던 경우 테스트 중 생성되지 않는다.

## 결과

`TMPDIR=/var/tmp uv run pytest -q tests/integration/test_bound_partial_forget.py tests/test_effect_knowledge.py --tb=short`: **10 passed / 8.90초**. 그중 새 실제 부분 삭제 조합은 4건, helper 예외 검증 6건이다. Ruff 전체·diff 통과. 초기 테스트 2건도 통과했고 Ruff import 정렬 지적을 수정한 뒤 최종 조합을 실행했다.

제품 소스 변경 없이 앞선 effect 상태 재결합의 부분 삭제·외부 철회 경계를 검증했다. 자동으로 모든 내용에 권한을 부여하는 동작은 추가하지 않았다. 모델은 실제 임베딩 대신 결정적인 시험 encoder를 사용하며 검색 품질 측정으로 해석하지 않는다.

정상 복원 상태, 처음 미검증 페이지의 부분 기록 상태, scoped page_access, crash/rollback, 실제 native 사용자 업무와 다른 에이전트 공유, 최신 설치 쌍·운영·M1–M14는 남는다. 전체 suite는 이번 테스트 추가 후 다시 실행하지 않았다. 운영 DB·서비스·공용 registry 변경과 push 없음.
