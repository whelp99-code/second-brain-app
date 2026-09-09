# 웹 배치 결과 안내

기존 `runPipeline()`은 저장 결과 영역에 배치 응답 JSON을 덮어썼다. 처리 상태별 안내가 없고, already_running인 경우에도 status가 ok이므로 필드를 해석해야 새 실행이 없었음을 알 수 있었다.

별도 처리 결과 영역과 상태 안내를 추가했다. 정상, 부분 실패, 한도 도달, 전체 실패를 구분하며 already_running을 먼저 해석한다. 알 수 없는 상태와 HTTP 실패는 완료라고 표시하지 않는다. 기억 저장 영수증과 업로드 결과는 보존한다. 실행 대기 중에는 두 실행 버튼을 비활성화하고 함수 중복 호출도 차단한다. 처리가 끝나면 기존 실패 상태 조회를 갱신한다.

실제 Chromium에서 현재 HTML을 로컬 서버로 열고 API 응답을 제어해 7개 상태를 검증했다. 각 요청 대기 중 두 번 추가 호출해도 7개 시나리오 전체 HTTP 요청은 7개였다. 두 버튼 복구와 저장 영수증 보존, pageerror 0을 확인했다. 의도적인 HTTP 500은 실패 안내 검증용이다. Browser plugin not available로 설치된 Playwright를 사용했다. 화면 `/var/tmp/sb-run-status.png`를 직접 확인했다.

`uv run pytest -q tests/test_web.py tests/test_run_all_partial.py`: **16 passed, 7.07초**. Ruff 및 diff 검사 통과.

브라우저 응답은 mock이다. 운영 배치나 LLM을 실행하지 않았으며, 개별 기억이 검색 가능한지의 인수와 구분한다. 기존 서버/API 계약은 변경하지 않았다. 최신 설치 후보에는 이 웹 변경이 아직 포함되지 않는다.
