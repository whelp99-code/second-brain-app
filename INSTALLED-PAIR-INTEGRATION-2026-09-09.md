# 설치된 provider와 새 자비스 후보 통합 — 2026-09-09

## 확인한 동작

세컨드브레인 wheel 설치본과 새 lock 기반 자비스 컴파일 후보를 함께 실행했다. 이전 개발 소스 검증의 공백을 줄였다. 정확한 provider manifest, import 경로, 자비스 build 경로와 결과는 동명 JSON에 기록했다.

- provider release `dc591781612a0e9acbc751aa2c6cc7b7b7b15093` (제품 소스 커밋 `b025e05888f5886460ab0457fb894a0ffd872d07`).
- 자비스 `/var/tmp/jarvis-locked-candidate-j9w0jrk8/source/dist`: 이전 단계에서 신규 설치·컴파일한 후보.
- 설치본의 MCP, CLI, executor, scoped write 모듈 4개의 실제 import 경로가 해당 release의 site-packages 안인지 검사했다.
- 정상·접수 중 철회·실행 전 철회·실행 전 만료 4개 경로 통과. 정상 요청 proved→settled→completed, 완료 반영과 시도 각각 1회, 재확인 시 중복 완료 없음.
- 다른 reader agent와 새 로그인으로 동일 generation의 기록 2개 조회. 독립 stdio SDK 클라이언트 2개가 각각 같은 2개 기록을 읽었다. reader 권한 철회 후 HTTP 403. FK 오류 0.

## 재현 도구

`deploy/check-release-integration.py ABS_PROVIDER_RELEASE ABS_JARVIS_BUILD`를 추가했다. stdlib Python으로 실행한다. 현재 커밋의 scripts/tests/contracts만 임시 디렉터리에 복사하고, `.venv`는 provider 설치본으로 연결한다. `sb/` 개발 소스는 복사하지 않는다. 사용자 Python site 경로는 차단한다. 임시 fixture는 종료 시 삭제한다. 자비스 build는 부모 디렉터리에 fixture config가 있고 build/node_modules가 새 설치 의존성을 가리키는 기존 acceptance 레이아웃이어야 한다.

첫 실행은 자비스 fixture의 cwd 설정 파일이 없어 실패했다. 검증 도구의 Node 실행 cwd를 자비스 후보 루트로 수정한 뒤 전체 4개 경로가 통과했다. Python 서버는 계속 소스가 없는 임시 harness에서 실행한다. 수정 후 Ruff 검사도 통과했다.

## 남은 범위

설치본 Python과 실제 제품 MCP/CLI 함수를 실행하지만 fixture 시각 주입을 위해 임시 launcher를 사용한다. 운영 bin launcher의 실제 설정과 systemd 실행까지 검증한 것은 아니다. 자비스는 아직 봉인된 운영 릴리스가 아닌 신규 의존성 컴파일 후보다. 모델 호출은 없고 신원 전달·정책·시각·검토된 내용은 fixture다. 운영 데이터·서비스·current는 변경하지 않았다. 실제 계정 연결, 운영 DB 전환/복구와 전체 릴리스 gate가 남아 있다.
