# 전체 배치의 부분 실패 상태 보존

웹 처리 결과를 점검하던 중 `sb.pipeline._run_all_mutable`의 결과 선택 결함을 확인했다. 수집 또는 컴파일이 `partial`이어도 후속 단계의 `ok`가 반환될 수 있었다. 수집 partial + 컴파일 capped도 오류가 없는 capped 결과로 덮였다. 수정 전 세 회귀가 실패했다.

전체 실패(exit_code 비정상)를 먼저 반환하는 기존 동작 이후, 부분 실패한 단계가 있으면 그 단계의 RunOutcome을 반환한다. 실행 ID·오류 수·원장 기록을 그대로 연결하며, 부분 실패의 기존 exit_code 0 계약은 변경하지 않는다. 부분 실패가 없을 때 capped/ok 선택은 기존 규칙을 유지한다. 단계 실행 순서나 저장 동작은 바꾸지 않았다.

검증:

- 결과 조합 네 개: 수집 partial, 컴파일 partial, partial+capped, partial+failed. 수정 전 3 failed/1 passed → 수정 후 통과.
- 실제 임시 vault와 `_run_locked`를 사용한 수집/컴파일 원장 기록: 수집 3건 중 오류 1건의 StageReport 이후 정상 컴파일을 실행해도 반환 상태 partial, errors 1, exit_code 0이며 해당 run_id 원장도 partial임을 확인. 입력 stage만 결정적으로 공급했고 LLM이나 운영 원본은 사용하지 않았다.
- CLI·웹·MCP 및 최초 네 회귀: **78 passed, 13.97초**.
- 실제 원장 사례 추가 후 집중 검사: **5 passed, 0.50초**. 앞선 네 회귀와 중복이며 고유 총수는 79개다.
- Ruff 및 diff 검사 통과.

운영 서비스는 변경하지 않았다. `read_status`의 마지막 단계 로그는 별도 표면으로 남으며, 이번 수정은 `run_all`의 반환 결과 보존에 한정된다. 실제 사용자가 웹에서 저장→처리→검색을 완료하는 전체 인수나 운영 준비 완료를 의미하지 않는다.
