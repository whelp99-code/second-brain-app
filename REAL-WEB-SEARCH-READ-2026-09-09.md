# 실제 웹 서버 검색→본문→빈결과 인수

소스49b419b의 실제 build_server와 임시 Git/원장/원본CAS를 사용했습니다. 기존 웹 fixture가 계약문서/충돌/일간문서를 실제 저장하고, 독립 Chromium에서 화면의 검색 버튼 및 전체열기 버튼을 클릭했습니다. API mock이나 route interception은 사용하지 않았습니다. 업무 내용은 fixture이며 운영 데이터는 아닙니다.

Browser plugin not available로 Playwright1.62.1을 사용했습니다. URL http://127.0.0.1:34789/, viewport1280x900, 제목Second Brain. 검색어 웹콘솔계약검색으로 결과1개·wiki/계약-일정 선택을 확인했습니다. 전체열기는 실제 /api/pages 요청으로 frontmatter/body를 반환했고 본문 검색어와 notes:wiki/계약-일정.md 출처 참조를 검증했습니다. 존재하지 않는 검색어의 results[] 이후 이전pageId/본문이 모두 비워졌습니다. pageerror/console warning/error0개입니다.

스크린샷 /var/tmp/sb-real-web-read.png, 임시 실행 스크립트 /var/tmp/sb-real-web-read.cjs. 서버는 tests.test_web._running context로 시작·종료했고 Chromium도 종료했습니다. 실제검색/본문 서버 경로의 UI 연결을 확인한 것이며 모델 임베딩 품질·사용자 업무 정답·모바일전체흐름·운영 배포는 별도입니다. 운영DB·서비스는 변경하지 않았습니다. 제품 코드 변경 없이 검증 증거를 추가합니다.
