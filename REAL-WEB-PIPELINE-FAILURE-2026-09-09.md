# 실제 웹 서버 저장·배치 실패 인수

제품 기준 `cae9021`. 임시 vault와 별도 상태 디렉터리를 생성하고 실제 `sb.web.build_server`를 실행했다. Playwright는 실제 버튼을 클릭했으며 HTTP 응답을 mock하거나 라우팅으로 대체하지 않았다. 모델 명령만 임시 경로의 존재하지 않는 실행 파일로 지정해 결정적인 장애를 만들었다. 운영 모델·설정·서비스는 사용하지 않았다.

1. 한글 제목과 내용을 입력하고 기억하기를 눌러 실제 inbox 경로 영수증과 처리 대기 안내를 확인했다.
2. 지금 처리를 눌러 실제 markdown connector→CAS/원장→배치 실행을 통과했다. 모델 명령 실패로 `failed`, errors 1, exit_code 1, pages 0을 반환했다. 후속 원장 조사에서 실패 단계는 **brief**로 확인했다. 초기 보고서의 compile 실패로 읽힐 수 있는 설명을 정정한다.
3. 화면에 처리 실패 안내와 미해결 실패가 나타났고 기존 inbox 영수증이 보존됐다.
4. 같은 한글 검색어로 실제 검색 API를 호출해 결과 0건을 확인했다.
5. 서버 종료 후 원장의 실제 source item 및 CAS 바이트를 확인해 입력한 한글 원문이 보존됐음을 검증했다.

브라우저 pageerror 0. 화면 `/var/tmp/sb-real-web-failure.png`를 직접 확인했다. Browser plugin not available로 기존 설치 Chromium/Playwright를 사용했다. 스크립트는 `/var/tmp/sb-real-web-failure.cjs`, 임시 vault는 JSON 증거의 workspace에 보관했다. 서버와 브라우저는 검증 후 종료했다.

[실행 ID·영수증·결과 증거](REAL-WEB-PIPELINE-FAILURE-2026-09-09.json).

이번 결과는 실제 제품 경로의 장애 인수다. 정상 모델 처리→검색→본문 조회 및 사용자 실업무의 에이전트 간 공유를 완료했다는 증거로 확대하지 않는다. 후속 [재처리 보류 확인](WEB-BRIEF-RECOVERY-HOLD-2026-09-09.md)에서 모델 명령 변경만으로 복구되지 않음을 확인했다. 제품 코드는 변경하지 않았다.
