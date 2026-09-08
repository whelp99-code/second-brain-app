# 제한 기억의 기존 자비스 전송기 연결 — 2026-09-09

JARVIS `ff0aecc`, SB `687ecf6`. [실측 결과](SCOPED-SUPERVISED-TRANSPORT-2026-09-09.json).

## 완료한 연결

별도의 우회 transport 대신 기존 `createSecondBrainTransport`에 `scoped-record-read-v1`을 추가했다. 고정된 두 도구(read/search)의 계약 파일과 SHA-256 sidecar를 양쪽 리포에 저장했다. 로더는 고정 digest `2c0bc8a467cb3f89f7c8cdb7df0a4eceb9790250b05d3fecffc13fb485417a7b`를 대조한다. 이전 schema3/4/5/6/7의 계약 내용과 검사는 유지한다.

제한 프로필은 최초 실행 전부터 미지원 메서드·누락 claim·미지 인자를 거부한다. 서버 handshake에서도 실제 도구 목록·필수 claim·입력 스키마를 대조한다. 기존 제한 응답 소비자는 받은 원본 record를 요청/claim/삭제 이력/본문/만료/예산과 대조한다. 서버 stdio는 제한 프로필을 명시했는데 범위 설정이 없으면 시작을 거부한다. 데스크톱의 명시적 config 주입과 기존 프로필 선택 규칙은 유지한다.

## 실행 및 발견한 결손

기존 acceptance 스크립트를 실제 JARVIS 기본 launcher 실행으로 확장했다. 실제 발급 코드와 테스트 정책/세션에서 얻은 claim을 기존 전송기로 보냈다. Python MCP의 두 도구 schema handshake→조회·검색→Node 소비자 검증→transport.restart→다시 조회·검색이 통과했다. 각 호출 record 2개는 같은 기억을 반복 회수한 것이다. 응답은 앞선 직접 MCP 조회 결과와 canonical bytes가 일치한다. 요청·claim·본문 변조는 각 호출에서 거부됐다.

첫 실제 실행 실패는 가상환경 Python을 launcher 자체로 사용한 테스트 설정에서 발생했다. 전송기의 realpath 해석으로 기본 Python이 선택됐고, 해당 경로의 import를 직접 재현하니 `ModuleNotFoundError: No module named 'anyio'`였다. 가상환경 실행 경로를 명시한 private shell launcher를 사용하여 기본 전송기의 경로 검증을 유지했다. 제품의 realpath 검사를 우회하지 않았다.

패키징 검사에서는 `scripts/copy-migrations.mjs`가 기존 schema6/7 계약도 복사하지 않는 것을 발견했다. 새 scoped 계약과 함께 명시적 복사 목록에 추가했다. 새로운 격리 디렉터리에 실제 복사 스크립트를 실행하여 JSON 5개와 sidecar 각각의 원본 bytes/digest 일치를 확인했다. 운영 dist나 migration 디렉터리는 변경하지 않았다.

## 검증 범위

- JARVIS: 전송 budgets/launcher/empty/crash/profiles/races/frozen, 새 scoped 및 adapter 연결 총 91 passed / 11 files / 6.20초.
- SB: 제한 MCP와 기존 프로필 호환 6 passed / 4.07초.
- TypeScript noEmit 및 격리 emit 통과, 변경 TS ESLint 통과.
- Ruff sb/tests 통과, 변경 SB 제품 모듈 basedpyright 0 errors/0 warnings.
- 실제 결과: `/var/tmp/page-access-acceptance-1m6srv8f/scoped-mcp-result.json`.
- 실제 패키징: `/var/tmp/scoped-contract-package-1skm1_nh/result.json`.
- 전체 SB/JARVIS 스위트나 실제 사용자 앱 로그인 흐름을 이번에 실행한 것은 아니다. fake compiler·합성 원본·고정 시각·테스트 authority DB와 세션을 사용했다.

## 남은 인수 및 보류

M1의 **전송 계약 연결**은 이번에 검증했다. 실제 인증 세션 공급자→현재 정책→issuer→전송→context의 제품 orchestration과 소비 직전 최신 권한 재확인은 남는다. 전송기 활성화만으로 기존 일반 read adapter가 제한 응답 형식을 처리하는 것은 아니므로 운영 프로필 일괄 전환은 보류한다. 새 소비자 검증기와의 제품 연결까지 마친 뒤 전환해야 한다.

M2 범위 쓰기/status/resolve/restore, M3 정책 rollback·기발급 claim 철회, M4 작업 성공 계보, M5 native 세션 수명, M6 외부 writer 및 나머지 실제 사용·운영 목표를 유지한다. 푸시·배포·서비스 재시작은 수행하지 않았다.
