# 기억 저장 응답 대기 중 새 초안 보존

발견: remember()는 성공 응답 후 textarea를 무조건 비워, 사용자가 응답 대기 중 새로 작성한 기억을 삭제했습니다. 실제 Chromium에서 API응답을 지연한 뒤 새 내용을 입력해 수정 전 빈 문자열이 되는 실패를 재현했습니다.

변경: 요청 시 제목/내용을 캡처하고, 성공 시 현재 제목/내용이 전송한 값과 모두 같을 때만 내용 입력창을 비웁니다. 내용이나 제목을 변경했으면 유지합니다. 실패 시도 입력을 보존합니다.

환경: Browser plugin not available — 세션에 Browser plugin/skill이 없어 일반 Playwright1.62.1/Chromium을 사용했습니다. 실제 sb.web._INDEX_HTML을 임시 HTTP서버로 제공했고 상태/저장 API는 Playwright route로 제어했습니다. 마지막 URL http://127.0.0.1:35911, 화면1280x900 및390x844. 서버/브라우저는 종료했습니다. backend 실제 저장 자체의 브라우저 검증은 아닙니다.

검사: 페이지URL/Second Brain제목, h1과실제form, 빈화면아님, 오류overlay없음, JavaScript pageerror0 확인. console오류는 의도한 실패400응답1개뿐이었습니다. 네 흐름(내용변경/제목변경/수정없는성공/실패) 모두 통과했습니다. 데스크톱 새초안 보존 스크린샷 /var/tmp/sb-draft-preservation.png, 모바일 /var/tmp/sb-draft-preservation-mobile.png. 실행 도구 /var/tmp/sb-draft-browser.cjs. 테스트는 버튼 클릭→제어된응답→DOM값검사로 수행했습니다.

HTTP회귀 tests/test_web.py tests/test_web_status_pin.py12 passed(7.51초), Ruff sb/tests통과. 이번 변경은 화면의 초안 보존이며, 기억의 provider처리 완료나 여러 에이전트의 실제 업무 인수 증거로 확대하지 않습니다. 운영 서비스·DB는 변경하지 않았습니다.
