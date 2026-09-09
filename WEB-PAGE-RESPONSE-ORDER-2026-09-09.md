# 페이지 본문 응답 순서 보호

새 검색이 끝난 뒤 이전 전체열기 응답이 늦게 도착하면 새 결과 아래에 이전 본문을 표시했습니다. Chromium 실제 DOM에서 이를 재현했습니다. 이제 새 검색마다 본문 요청 일련번호를 무효화하고, 본문 성공/실패는 최신 요청번호와 현재 pageId가 모두 일치할 때만 표시합니다. pageId 직접 편집 시 기존 본문/불러오는중 표시도 초기화합니다.

Browser plugin not available로 Playwright1.62.1을 사용했습니다. 실제 _INDEX_HTML을 임시127.0.0.1 HTTP로 제공하고 응답순서는 route로 제어했습니다. 1280x900 Chromium에서 Second Brain제목/검색form/본문DOM을 확인했습니다. 기존검색3흐름에 이어 새검색후이전본문 거부, 두페이지본문 역순응답 최신값유지 검사를 통과했습니다. pageerror0, /var/tmp/sb-page-order.png에서 현재pageId와최신본문을 확인했습니다. 이전검색오류 검사에는 의도한400응답을 사용했습니다. 임시스크립트 /var/tmp/sb-page-order.cjs, 서버/브라우저종료.

HTTP12개통과(7.78초), Ruff sb/tests 통과. 마지막 pageId input 초기화 추가 후 같은 브라우저 시나리오를 재실행했습니다. 실제backend본문 조회의 권한/출처 검증이나 모바일전체흐름 인수는 별도입니다. 운영 서비스·DB는 변경하지 않았습니다.
