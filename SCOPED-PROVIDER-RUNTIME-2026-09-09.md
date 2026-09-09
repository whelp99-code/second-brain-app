# Scoped provider 검증기를 일반 실행 명령에 연결

## 누락 경로와 구현

이전 HTTPS 인수는 RequestExecutor에 직접 콜백을 주입했다. 일반 sb apply-requests --once는 콜백을 구성하지 않아 scoped 요청을 처리할 수 없었다. 새 configured_scoped_provider_authority가 고정 Config의 [scoped_provider_verifier] credentials_path를 읽어 같은 HTTPS 채널과 실제 UTC 시계를 조합하고 CLI 실행기에 연결한다.

설정 섹션이 없으면 기존 legacy 구성 선택을 유지한다. 섹션이 있으면 credentials_path 하나만 허용하고 절대 경로와 제어문자 부재를 요구한다. enabled=false·사용자 session 라벨·잘못된 타입/추가 필드는 fallback하지 않고 SCOPED_PROVIDER_RUNTIME_CONFIG_INVALID로 종료한다. 이미 V4로 전환한 원장을 이 설정 제거로 이전 schema로 내리는 기능은 아니다.

요청 원장을 열거나 claim하기 전에 자격증명 파일 형식·소유권/비공개 권한·origin/token 형식과 TLS CA 설정을 검사한다. 사전 검사는 로컬 설정 검사이며 로그인/현재 정책의 허용을 보장하지 않는다. 매 수락·실행 검사에서 현재 자격증명 파일과 실제 gateway session/policy를 다시 확인하는 경로를 유지한다. 기존 JARVIS/provider 키 설정 요구도 유지한다.

## 사전 검사 중 추가 발견·수정

사용자 지정 CA 경로가 FIFO이면 OpenSSL의 파일 읽기에서 사전 검사가 멈추는 것을 별도 child의1초 timeout으로 재현했다. 해당 결함을 고치기 위해 진행 중이던 첫 전체 pytest를 SIGINT로 종료했다(136 passed/104.66초, 전체 성공이 아님).

CA를 nonblocking open한 뒤 descriptor가 최대256KiB의 비어 있지 않은 일반 파일인지 확인하고, 읽은 PEM 데이터를 TLS context로 전달하도록 수정했다. 공개 CA의 일반 파일 symlink는 허용하되 FIFO/디렉터리/크기 초과는 CA_INVALID다. 비공개 자격증명 파일의 symlink 금지는 유지한다. FIFO·디렉터리·크기 초과 회귀 검사는2초 제한을 둔 별도 프로세스에서 prompt rejection을 검증한다.

## 검증

- 최종 관련29개 통과(7.23초): runtime 설정/사전 검사와 HTTPS 실제 child 테스트.
- 전체 Ruff 및 runtime/HTTPS/CLI 모듈 basedpyright 오류0/경고0.
- [실제 TLS + 일반 CLI 경로 결과](SCOPED-PROVIDER-RUNTIME-2026-09-09.json): 정상 accepted→proved/HTTPS검사5회; 수락 중 철회는 CLI 실행 전에 수락 원장 없음/2회; 실행 전 정책 철회·로그인 만료는 CLI exit1/failed/활성 세대·proof 없음/각3회. 원래 attempt1/FK0 유지.
- CLI 인수는 별도 Python 프로세스에서 임시 SB_CONFIG를 실제 load_config/main(['apply-requests','--once'])로 읽었다. Runtime callback을 임의로 주입하지 않는다. 현재 시간과 request executor의 관측 시각만 fixture로 고정했으며, 운영 CLI에 테스트 시계 옵션을 추가하지 않았다. 게이트웨이 세션은 실제 발행, TLS/신뢰 전달자·시각/원래 dispatch는 임시 인수 환경이다.
- 최종 전체 pytest: **1,335 passed, 2 skipped / 303.28초**. 저장소 지침대로 optional embeddings 전용 tests/test_embeddings.py는 제외했다. 중단한 첫 실행이나 관련29개를 전체 결과에 더하지 않는다.

## 운영 경계와 다음 작업

README에 명시적 설정과 실행 명령을 추가했다. 운영 설정 파일이나 자격증명을 만들거나 변경하지 않았다. 자격증명 공급/회전, gateway 실행 설정, 공개 MCP scoped 쓰기 계약, 실제 에이전트 A 저장→B 새 세션 조회를 이어간다. 설정 검사 통과만으로 원격 로그인 readiness나 전체 공통 기억 완성을 판정하지 않는다.

첫 활성 세대 이전 상태 조회, 전체 원문/spool/로그/백업 삭제·복원 및 재유입 억제, 클라이언트별 수집/주입, 한글 검색 평가, GUI·운영 복구를 포함한 M1–M14 범위를 유지한다. 운영 DB/서비스/vault/기존 migration 변경, push/배포는 수행하지 않았다.
