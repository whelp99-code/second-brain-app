# 웹 검색 응답 순서 보존

최신 질문 응답을 먼저 반환하고 이전 질문 응답을 나중에 반환한 실제 Chromium 재현에서 pageId와 결과가 이전 기억으로 덮였습니다. 이제 검색 요청 일련번호로 최신 요청의 성공/실패만 반영합니다. 새 검색 시 이전 pageId와 페이지 본문을 초기화하고 검색중 상태를 표시합니다. 빈 결과에서도 이전 pageId를 남기지 않습니다.

Browser plugin not available이므로 Playwright1.62.1을 사용했습니다. 실제 _INDEX_HTML을 임시127.0.0.1 서버로 제공하고 API응답 순서를 route로 제어했습니다. 1280x900 Chromium에서 제목Second Brain/실제 검색form/결과DOM 확인, pageerror0입니다. 이전 성공의 늦은 도착, 빈결과, 이전 오류의 늦은 도착3흐름을 검증했습니다. 의도한400오류는 이전요청에만 주입했습니다. 스크린샷 /var/tmp/sb-search-order.png에서 최신질문/최신기억/선택페이지 일치를 확인했습니다. 임시 검증 스크립트는 /var/tmp/sb-search-order.cjs이며 서버는 종료했습니다.

HTTP회귀12 passed(7.65초), Ruff sb/tests 및 diff검사 통과. 실제 backend검색 정확도나 모든 비동기 화면 흐름의 인수는 아닙니다. 페이지 본문 별도 조회의 응답 순서, 모바일 상호작용 전체는 이번 범위에 포함하지 않습니다. 운영 서비스와 DB는 변경하지 않았습니다.
