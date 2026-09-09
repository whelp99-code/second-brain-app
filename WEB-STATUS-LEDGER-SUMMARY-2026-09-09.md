# 웹 상태 요약을 원장 실행과 일치시키기

/api/status의 status 문자열은 pipeline.read_status로 log.md를 읽었고 last_run_status 및 단계 이력은 status_snapshot의 SQLite 원장을 읽었다. log가 없거나 오래되면 실행 이력이 있는데도 no runs 또는 이전 로그를 표시할 수 있었다. 실제 HTTP 회귀에서 latest-failed 원장이 있는데 status=no runs로 재현했다.

웹 요약을 같은 snapshot의 last_run에서 구성한다. 최근 단계 실행 ID와 상태를 표시하고, 원장에 실행이 없을 때만 명시적으로 원장 실행 없음으로 표시한다. 전체 배치 완료를 의미하는 표현은 사용하지 않는다. CLI의 기존 로그 조회 동작은 이번 범위에서 바꾸지 않았다. 전체 배치 영속 요약은 별도 잔여 항목이다.

검증: web/ops/web run failure **38 passed / 10.42초**, Ruff/diff 통과. 이전 시간대 검증의 같은 임시 SQLite 저장소에서 실제 HTTP를 다시 호출해 status=no runs에서 최근 단계 실행 newer: ok로 바뀌고 상세 이력과 일치함을 확인했다. [변경 전후 응답](WEB-STATUS-LEDGER-SUMMARY-2026-09-09.json). 합성 원장 기록이며 HTTP 응답을 mock하지 않았다. 서버 종료, 운영 데이터 변경 없음.

실제 업무 공유·운영 전환·전체 M1–M14 인수는 남는다.
