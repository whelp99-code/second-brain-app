# 충돌 호출 한도 도달의 배치 상태 전달

충돌 checker는 호출 한도에 도달하면 남은 비교를 건너뛰지만 호출자에게 그 사실을 전달하지 않았다. pipeline의 capped 값은 컴파일 한도만 반영했다.

기존 list 반환 계약을 유지하고 선택적 `on_capped` callback을 추가했다. 실제 비교를 한도 때문에 생략할 때 pipeline의 capped 상태를 설정한다. 완료된 판정의 캐시 복원은 기존처럼 한도 검사보다 먼저 수행한다.

실제 임시 웹 서버에서 합성 입력과 로컬 모델 대역, 충돌 호출 한도 0을 설정해 저장→처리를 실행했다. `/api/run`은 **capped, pages1, errors0, exit_code0**을 반환했다. [실행 증거](CONFLICT-CAP-OUTCOME-2026-09-09.json). HTTP 응답 mock은 없었다. 마지막 브리핑 단계는 ok이므로 `/api/status`의 last_run_status와 전체 배치 결과의 범위 차이는 여전히 남는다.

호출 한도 테스트에 생략 통지를 확인하는 회귀를 추가했다. 충돌·CLI·배치·재시도 관련 **72 passed, 5.44초**, Ruff/diff 통과. cap을 늘리거나 운영 서비스를 변경하지 않았다. 모델 정확도·전체 운영 인수는 미완료다.
