# OpenCode snapshot 읽기 실패 격리

OpenCode scan은 path.stat 또는 _read_snapshot의 OSError를 처리하지 않아 한 파일의 읽기 실패가 전체 scan을 중단했다. 별도 Python 프로세스에서 HEAD의 이전 모듈을 로드하고 새 회귀 검사를 실행하자 simulated read failure가 scan 밖으로 전파되어 실패했다. 작업공간 소스를 되돌리지 않고 이전 구현의 동작을 확인했다.

파일별 읽기 오류를 unreadable-session-file로 보고하고 그 파일의 이전 cursor를 유지하도록 수정했다. 다른 snapshot은 계속 수집하고, 다음 scan에서 읽기가 복구되면 실패했던 파일만 회수한다. snapshot binary 읽기에 기존 open_session_file의 비차단·no-follow·일반파일 검사를 재사용했다.

검증: 실패 파일+정상 형제에서 정상 본문 수집, 실패 cursor0 유지, 복구 후 실패 본문1개만 회수. 실제 별도 프로세스에서 크기 확인 후 snapshot을 FIFO로 교체해도 대기 없이 읽기 오류·cursor0을 확인했다. OpenCode/세션/교체 회귀 **43 passed / 0.65초**. Ruff sb/tests·변경 모듈 basedpyright0오류0경고·diff 통과.

이번 범위는 읽기 실패와 특수 파일 교체다. 현재 snapshot cursor의 크기 기반 변경 감지, 참조 SQLite 데이터의 별도 변경·경로 경계, 파일 읽기 상한은 후속 검토 대상이며 이 수정으로 해결됐다고 주장하지 않는다. 운영 계정·세션·서비스 변경 없음. 전체 회귀/설치물 이후 제품 변경이며 사용자 업무·M1–M14 인수는 유지한다.
