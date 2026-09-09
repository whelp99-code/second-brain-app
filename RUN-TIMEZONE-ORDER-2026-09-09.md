# 실행 상태 이력의 시간대 정렬 수정

상태 조회와 Ledger.list_runs가 started_at 문자열을 정렬했다. 같은 날짜의 `23:00+09:00`을 `15:00+00:00`보다 최신으로 선택하지만 실제로는 한 시간 이전이다. 혼합 시간대의 합성 원장으로 last_run=older 오류를 재현했다.

공통 run_time_key가 UTC·고정 마이크로초 형식으로 변환한다. 원장 조회, 상태의 last_run, SQLite 최근 단계10건 조회에 같은 기준을 적용한다. 저장한 원래 시각은 변경하지 않는다. 기존 naive 시각은 UTC로 처리하며 잘못된 시각은 최신으로 승격하지 않고 정렬상 가장 오래된 것으로 취급한다. 같은 시각은 기존 run_id 정렬을 유지한다.

검증: 관련 ops/web/store ledger **54 passed / 10.04초**, Ruff/diff 통과. 같은 순간의 다른 offset, naive UTC, 마이크로초 순서, 잘못된 시각을 검사했다. 별도 임시 SQLite 원장과 실제 HTTP `/api/status`에서 newer→older 이력을 회수했다. [실행 증거](RUN-TIMEZONE-ORDER-2026-09-09.json). 실행 기록은 합성이며 원장/API를 mock하지 않았다. 서버는 종료했고 운영 데이터는 수정하지 않았다.

추가 발견: 실제 API는 최근 단계와 last_run_status=ok가 있는데 status 문구는 no runs였다. 이번 합성 기록에는 pipeline 로그가 없으므로 요약이 별도 로그에 의존하는지 후속 대조가 필요하다. 이번 수정으로 전체 배치 요약의 일관성까지 해결했다고 주장하지 않는다. 운영 전환·실제 업무 공유·M1–M14는 남는다.
