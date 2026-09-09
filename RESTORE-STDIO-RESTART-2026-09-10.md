# 복원 기억의 별도 MCP 프로세스 재시작 검증

기준 제품 31c5bb8. 복원 및 scoped MCP 검증을 서로 다른 서버 프로세스로 확장했다. 테스트 전용 entry point tests.restore_stdio_server는 fixture 설정과 고정 시각만 로드한 다음 실제 sb.mcp.build_server().run()을 실행한다. Python 실행 파일로 두 번 별도 서버를 시작하고 MCP stdio Client를 연결·종료한다. 두 번째 서버는 첫 번째 서버의 Python 메모리를 공유하지 않는다.

정상 복원 및 지식 상태/출처 분류/페이지 접근 정보 저장 직후 오류→동일 요청 재시도의 네 경로 모두에서, 새 서버 두 개의 정상 응답 전체가 동일하고 살아남은 기억 본문이 들어 있는지 확인했다. 각 서버에서 다른 프로젝트의 서명된 요청은 오류이며 본문을 포함하지 않는다. 기존 동일 프로세스 검증의 사용자/정책/만료/키 철회 검사도 유지한다.

`TMPDIR=/var/tmp uv run pytest -q tests/integration/test_memory_restore_reingress.py --tb=short`: **6 passed / 22.21초**. 총 여덟 번의 별도 서버 실행을 포함한다. Ruff 전체·diff 검사 통과. 제품 코드 변경 없음. 최신 전체 suite 근거는 제품 5838b77의 1,674통과/2skip이며 새 테스트 추가 이후 전체 재실행은 하지 않았다.

한계: 테스트용 고정 키·시각·합성 기억을 사용한다. 실제 JARVIS DB에서 발급한 권한, HTTPS 연결, native 에이전트 로그인과 사용자 업무 수행 검증은 아니다. 정상 프로세스 재시작을 강제 종료·전원 장애 인수로 표현하지 않는다. 운영 DB·서비스·공용 registry·다른 리포 변경과 push 없음. JARVIS 실제 연결·운영/DR 및 전체 M1–M14 목표는 남는다.
