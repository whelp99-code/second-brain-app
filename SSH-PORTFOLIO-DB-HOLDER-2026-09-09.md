# SSH 세션의 운영 DB 보유 원인 — 2026-09-09

직전 열린 핸들 관측의 PID1553366을 /proc에서 다시 확인했다. 실행 파일은 Node24.19.0, 스크립트는 control-center의 artifact-4146a192b5fb9e489e2ce3fcb9629077739df0134bc26094750628369dcfdb98/dist/src/cli.js다. 부모 PID1553350은 sshd-session, cgroup은 session-73884.scope였다. 명령줄 전체/환경/키 값 대신 소스에 정의된 명령 단어와 대조하여 portfolio/ingest만 확인했다. stdin은 pipe, 관측 wchan은 ep_poll이다.

같은 시점 다른 DB 보유 프로세스는 jm-jarvis-dashboard.service와 jm-jarvis.service였다. 따라서 운영 전환 전 named unit 검사 외에 SSH/수동 CLI 연결을 조사해야 한다. 이 PID는 미래 종료 대상으로 사용하지 않으며 재확인이 필요하다.

현재 src/cli-runtime.mts는 AuthorityDb를 열고 command handler를 실행한다. cli-core-commands.ts의 portfolio ingest는 readiness/key 확인 후 readPortfolioStdin을 await한다. src/dashboard/portfolio-stdin.ts는 크기 제한만 검사하며 for-await 종료까지 시간 제한이 없다. 운영 해당 릴리스의 portfolio-stdin.js도 timeout이 없는 구현이었다. 이는 열린 입력이 DB 연결 수명을 무한히 늘릴 수 있는 코드 경로의 증거다. /proc wait 채널만으로 현재 프로세스의 정확한 JS stack을 증명하지는 않는다.

다음 구현 범위: portfolio 입력 대기에 유한한 deadline을 두고, timeout/중단에서 스트림과 DB 수명이 종료되며 부분 입력을 ingest하지 않도록 검증한다. 기존 데이터 전송 크기·정상 완료를 유지하고 재시도는 자동 실행하지 않는다. 정책상 시간 값은 기존 호출자 특성과 대조한다.

이번에는 프로세스 종료·stdin 입력·서비스 재시작·DB 변경을 하지 않았다. 접근 불가 프로세스와 다른 사용자/원격 클라이언트 범위도 여전히 남는다. 전체 운영 전환은 미완료다.
