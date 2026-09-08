# 인증된 scoped reader의 CLI context 연결

2026-09-09. JARVIS 제품 `e932f79`, SB 인수 `7c3fcae`.

기존 `memory context`는 일반 production reader만 생성했다. CliDependencies의 명시적인 scopedMemoryReferenceOptions를 통해 기존 createProductionScopedMemory를 선택하도록 연결했다. 신뢰된 호스트가 authenticated_session 공급자·현재 정책 파일·기존 키·전송 설정을 제공한다. 일반 memoryReferenceOptions와 동시에 지정하면 MEMORY_REFERENCE_CONFIG_AMBIGUOUS로 거부한다. scoped 초기화/인증 실패 시 일반 조회로 fallback하지 않는다.

명령의 기존 query/limit/전체 JSON 예산, transport 정리 후 최종 권한 검사와 privacy/세대 검증을 재사용한다. 외부 MCP 계약, 원장 스키마, 기존 기본 CLI 동작은 바꾸지 않았다. agent/session 명령행 문자열이나 환경변수를 인증 신원으로 해석하는 기능을 추가하지 않았다.

## 검증 결과

- JARVIS 관련 **27 passed / 3 files / 18.71초**: scoped production, reference read/CLI, scoped client. 인증 누락과 설정 혼합을 provider 시작 전에 거부했으며 기존 일반 CLI 예산·정리 검사가 통과했다.
- TypeScript 격리 emit·변경 파일 ESLint·JavaScript 구문·양쪽 diff 검사 통과.
- 실제 격리 TypeScript의 CLI execute → 제품 factory → 실제 Python stdio MCP에서 `memory context Cited --max_bytes 32768` 실행: records 2개, 버전/metadata/개행을 포함한 출력 예산 준수.
- 같은 실행에서 phone 쿠키를 제거한 뒤 CLI를 다시 호출하면 MEMORY_ACCESS_SCOPE_UNAVAILABLE. 일반 reader로 우회하지 않았다.
- 기존 v1/v2 인수, 빈 결과 세대 변조, 응답 후 정책 철회, 독립 프로세스 중복 제출 거부를 함께 재실행했다.
- 인수 원본: `/var/tmp/page-access-acceptance-7aj5at1e/scoped-mcp-result.json`. [보존 JSON](SCOPED-CLI-CONTEXT-2026-09-09.json).

## 이번 누적 전체 검사

SB `397bc87`의 Python 제품/테스트 기준으로 `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`를 실행하여 **1,142 passed / 2 skipped / 216.57초**를 확인했다. 로그 `/var/tmp/shared-memory-september9-full-current.out`. 이후 이 턴의 SB 변경은 JavaScript 인수와 문서이며 Python 제품/테스트를 수정하지 않았다. `uv run ruff check sb tests`도 통과했다. 선택적 embeddings extra 검증은 제외했으며 전체 JARVIS suite 통과 수치로 해석하지 않는다.

## 지원 범위와 다음 단계

이 연결은 기존 CLI의 프로그램 실행 API에 대한 구현이다. 독립 `jarvis` 프로세스가 사용자 세션을 인증하는 기능은 아직 없다. 인수는 CLI execute를 실제 호출하지만 호스트가 시험용 phone store/정책/키/시계를 제공하고 합성 원본·fake compiler를 사용했다. 운영 로그인·운영 데이터·모델 native 세션 인수는 아니다.

현재 provider의 mcp_scoped_read는 연결마다 한 세션을 고정하며 JARVIS 파일 정책도 해당 세션을 명시적으로 허용한다. 따라서 임의 로그인 세션에 자동으로 프로젝트 권한을 배정하거나 일반 CSRF를 scoped 인증으로 바꾸지 않는다. 실제 호스트 인증 진입점에서 세션별 정책/전송 수명을 구성하고 이 API를 호출하는 것이 다음 연결 단계다. 게이트웨이와 backend가 별도 프로세스인 HTTP 경로에는 검증된 세션 전달 경계가 추가로 필요하다.

CLI context 반환은 모델이 실제로 수신한 영수증이나 native session 중복 제출의 증거가 아니다. 실제 모델 공급은 기존 submitInSession 경로와 관측된 client/session/epoch를 사용해야 한다. scoped 쓰기→검증 결과→영수증→새 에이전트 재사용, 정책 rollback·원문/로그 삭제·복구·클라이언트별 실제 인수 등 전체 목표를 유지한다. 운영 배포/서비스 재시작/운영 DB 변경은 하지 않았다.

## 후속: 실제 provider 종료 중 인증 철회

2026-09-09 인수 코드 `c0105db`. 제품 JARVIS `e932f79`는 추가 수정하지 않았다. 실제 node execFile로 생성한 MCP 자식의 exit 이벤트에서 시험용 현재 쿠키를 제거하고 CLI 실행 결과를 검사했다. 자식 종료가 실제 관측됐으며 최종 결과는 MEMORY_ACCESS_SCOPE_UNAVAILABLE로 거부됐다. 읽기 응답을 이미 받았더라도 owned transport 정리 후 최종 인증 검사에서 문맥 출력을 차단함을 확인했다. mock close나 sleep을 사용하지 않았다.

정상 CLI records 2/예산 준수, 쿠키 누락 거부, 기존 v1/v2·세대/정책 철회·독립 프로세스 중복 제출 검사를 같은 실행에서 재확인했다. JavaScript 구문과 diff 검사 통과. 전체 Python/JARVIS 테스트를 다시 실행하지 않았으며 위 전체/집중 검사 수치는 앞선 실행 기록이다. 최신 원본 `/var/tmp/page-access-acceptance-k7176aqi/scoped-mcp-result.json`을 연결 JSON에 보존했다.

현재 제품 호출 지점을 다시 검색한 결과 phone 세션 공급자에서 scoped factory로 이어지는 HTTP 구성이 없고, standalone CLI도 scopedMemoryReferenceOptions를 생성하지 않는다. 다음 작업은 이 실제 호스트 연결과 세션별 명시 정책 구성이다. 현재 검증을 실제 로그인 완료나 모델 전달/보존 수명 인수로 확장하지 않는다.
