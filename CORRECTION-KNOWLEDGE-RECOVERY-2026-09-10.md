# 정정 후 상태 저장 실패의 재처리 인수

기준 제품 99feecb. 기존 remember→correct→export→forget 통합 테스트에 정정 상태 저장의 일시적 실패를 추가했다. 제품 코드는 변경하지 않았다.

최초 페이지 전체 상태는 컴파일과 동일한 본문 digest를 fixture로 기록한 것이며 실제 모델 실행은 아니다. 그 뒤 접수·정정·proof·검색·내보내기·삭제는 실제 provider 경로를 사용한다. lexical/hybrid별로 미승인 정상, 승인 정상, 승인+실패복구의 총 6경우다.

실패복구에서는 정정의 erasure 처리 이후 Ledger.bind_knowledge를 RuntimeError로 실패시킨다. 요청이 reconciling이고 현재 세대가 유지되며 tombstone high water는 기록돼 있음을 확인한다. 오류 injection을 제거하고 executor를 닫은 뒤 새 객체로 원장을 다시 열어 lease 만료 후 같은 요청을 실행한다. proved 완료 및 high water 불변을 확인했다. 시간은 명시적으로 진행하며 sleep을 사용하지 않는다.

복구 뒤 정정 문장은 wiki 페이지에 정확히 한 번 저장된다. 이전 내용은 관리형 bytes에 없고, hybrid record_vectors도 새 기록 1개만 가진다. 승인된 본문은 active VERIFIED로 조회되며 기존 미승인 경로는 승격되지 않는다. 이후 export·forget·최종 proof/inventory/MCP 상태 검사를 기존과 동일하게 수행했다.

`TMPDIR=/var/tmp uv run pytest -q tests/integration/test_memory_lifecycle.py --tb=short`: **6 passed / 27.13초**. Ruff 전체·diff 통과. 중복 문장 검사를 추가하기 전 실행도 6개 통과했으나 최종 숫자는 추가 후 재실행이다.

이 검증은 같은 OS 프로세스 안에서 executor 객체와 DB 연결을 다시 생성한 것이다. SIGKILL·전원 손실·다른 바이너리 재시작 검증으로 해석하지 않는다. 영구 저장 오류, 취소와의 경쟁, 정상 복원 상태, scoped 접근, 실제 사용자 업무·다른 모델·최신 설치·운영과 M1–M14는 남는다. 전체 suite는 이번 테스트 추가 후 다시 실행하지 않았다. 운영 DB·서비스·공용 registry 변경과 push 없음.
