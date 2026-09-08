# 인증된 phone HTTP → scoped 기억 문맥 연결

2026-09-09. JARVIS 제품 `939a0d9`, SB 결정·인수 `33f2a07`.

기존 phone gateway는 인증 쿠키를 upstream에 전달하지 않았고 공통 CSRF만 사용했다. 새 선택적 POST `/api/v1/memory/context`는 같은 gateway 프로세스의 기존 세션 저장소에서 인증된 기억 세션을 구성하여 기존 CLI context API와 scoped product factory를 호출한다. 별도 upstream에 신원 헤더를 전달하지 않는다. 기존 일반 search/detail/status/conflicts proxy의 동작과 권한 의미는 변경하지 않았다.

## 구성과 사용 조건

`createPhoneGatewayServer`의 선택적 `memoryContext`에 기존 database_path, 서버가 정한 agent_id, 기존 scoped memory 정책/키/전송 설정을 제공한다. server 설정이 없으면 이 경로는 503으로 거부한다. 신규 DB/키/프로젝트 권한을 자동 생성하지 않는다. standalone phone CLI/deploy 환경설정에서는 아직 이 옵션을 읽지 않는다.

요청 본문은 정확히 다음 네 필드다.

```json
{"schema_version":1,"query":"Cited","limit":8,"max_bytes":32768}
```

질문은 NFC/trim·1~512 bytes, limit은 1~32, max_bytes는 1,024~65,536이다. 쿠키·Tailnet owner·Origin·CSRF·POST 본문 크기·rate limit은 기존 gateway 검사를 재사용한다. 신원·project/session 문자열을 요청에 추가하면 거부한다. 별도 scoped context 동시 실행은 서버당 8개로 제한한다. CLI 응답 예산과 최종 인증·세대·privacy 검사를 재사용하고 HTTP 응답 포장 분량도 대조한다.

## 실행 검증

- 관련 **46 passed / 4 files / 5.18초**: gateway unit, HTTP, memory adapter, scoped production. 미구성 503과 요청 신원 삽입 400 및 기존 경로 회귀 통과.
- TypeScript 격리 emit, 변경 TypeScript ESLint, JavaScript 구문, 양쪽 diff 검사 통과.
- 격리 빌드 실제 HTTP에서 phone session 쿠키 발급 → 시험 운영자가 그 세션을 명시적으로 허용 → POST context → CLI → 실제 Python scoped MCP → records **2개 / HTTP 본문 4,649 bytes** 반환.
- 쿠키 누락 401, CSRF 누락 403, 요청 agent_id 삽입 400. 새 로그인 세션에 기존 세션 정책을 재사용하면 거부. 현재 정책에서 세션을 제거해도 본문 반환 거부.
- 초기 인수에서는 정책 미등록/철회가 공통 502였으며, 아래 후속 수정에서 403으로 분리했다. 원문이나 내부 예외 내용은 반환하지 않는다.
- 새 context 요청이 기존 fake authority proxy에 전달되지 않았음을 capture로 확인했다. MCP는 실제 supervised child를 사용했다.
- 기존 v1/v2, CLI 정리 중 철회, 예산, 세대 대체, 독립 프로세스 중복 제출 거부도 같은 인수에서 재실행했다.

[보존 결과 JSON](SCOPED-PHONE-HTTP-CONTEXT-2026-09-09.json). 원본 `/var/tmp/page-access-acceptance-1flv_9sl/scoped-mcp-result.json`.

재현은 기존 `TMPDIR=/var/tmp uv run python scripts/scoped-mcp-acceptance.py <격리 JARVIS 빌드 경로>`를 사용한다. 새 helper `scripts/scoped-phone-http-acceptance.mjs`는 시험 운영자 역할로 발급된 쿠키의 기존 HMAC/기억 세션 ID를 계산하여 **시험용 복사 정책과 provider 설정만** 명시적으로 작성한다. 이는 제품의 자동 권한 배정 기능이 아니며 운영 정책을 바꾸지 않는다.

## 아직 완료되지 않은 범위

실제 HTTP 쿠키 인증과 MCP를 연결했지만 Tailnet 헤더·owner/key·프로젝트 정책·원본·시각은 fixture이고 compiler는 fake다. 실제 Tailnet 접속이나 운영 데이터 인수를 의미하지 않는다. 서버는 session별 provider 설정을 요구하며 현재 새 로그인에 대한 정책 배정과 standalone 활성화 설정이 남는다. 현재 읽기 문맥 API에는 요청 취소에 따른 즉시 provider 정리·실제 배포 설정 검증도 추가로 필요하다.

같은 프로세스에서 기존 DB와 signer를 사용할 수 있는 명시적 server 구성만 지원한다. 운영 credential 접근·서비스 경계는 배포 전 별도 대조해야 한다. 기존 proxy 전체를 scoped로 광고하거나 사용자 입력 신원을 권한으로 사용하는 것은 보류한다. 모델이 실제 참고 기억을 수신한 증거는 submitInSession과 관측된 native session/epoch로 따로 인수한다.

scoped 저장→검증 결과→영수증→새 에이전트 재사용, 정책 rollback, 정정/삭제·모델 로그·복구, 실제 클라이언트별 지원 및 전체 M1~M14 목표를 유지한다. 이번에 운영 배포·서비스 재시작·운영 DB/설정 변경·push를 하지 않았다. 이전 전체 SB 1,142통과/2skip는 앞선 Python 제품 기준이며 이번에 전체 suite를 재실행한 것은 아니다.

## 후속: 오류 분류와 실제 세션 만료 우선 처리

2026-09-09 JARVIS `55bc647`, SB 인수 `cb637e7`. 허용된 내부 오류 타입·코드만 HTTP 분류에 매핑하며 unknown 오류는 기존 일반 502 처리로 보낸다. 예외 메시지나 경로·키·provider 본문을 응답에 복사하지 않는다. 처리 중 오류가 발생하면 현재 쿠키를 먼저 재인증하여 로그인 만료는 정책 오류보다 우선 401로 반환한다.

| 조건 | HTTP | 의미 |
|---|---|---|
| 현재 로그인 만료 | 401 + 만료 쿠키 | 로그인 세션 필요 |
| 정책 미등록·철회·scope 변경 | 403 PHONE_MEMORY_SCOPE_FORBIDDEN | 현재 세션의 허용 정책 필요 |
| 질문·분량 입력 오류 | 400 PHONE_REQUEST_INVALID | 요청 수정 필요 |
| 세대·privacy·억제·만료된 문맥 | 409 PHONE_MEMORY_CONTEXT_CHANGED | 현재 상태를 새로 확인해야 함 |
| 문맥 서비스 동시 실행 상한 | 429 PHONE_CAPACITY_EXCEEDED + Retry-After: 1 | 대기 후 재시도 가능 |
| provider/개인정보 상태 불가, 필수 설정·키 불가 | 503 | 서비스 준비 상태 확인 |

관련 **61 passed / 4 files / 2.86초**, TypeScript 격리 emit·변경 파일 lint·구문·diff 검사 통과. 이 중 오류 분류 단위 검사는 16개이며 전체 JARVIS 회귀 수치가 아니다. 실제 HTTP/MCP에서는 정상 records2/4,649bytes, 정책 철회·미허용 새 세션 403, 잘못된 질문400, 쿠키/CSRF 누락 거부를 확인했다. 실제 MCP 자식 exit 이벤트에서 시험 시계를 16분 이동하면 401 PHONE_SESSION_REQUIRED와 만료 쿠키가 반환됐다. 에러 반환 중 본문 노출 없이 로그인 만료를 먼저 처리했다. sleep으로 만료를 기다리지 않았다. 409/429/503의 전 조건은 이번 실제 MCP 시나리오로 실증한 것은 아니며 분류 단위 검사 범위다.

최신 원본은 `/var/tmp/page-access-acceptance-27ktkz5w/scoped-mcp-result.json`, 연결 JSON을 갱신했다. 기존 CLI·v1/v2·세대 대체·철회·독립 프로세스 중복 거부 인수도 같은 실행에서 유지됐다. 운영 Tailnet·정책·DB를 사용하거나 배포하지 않았다. standalone 활성화, 정책 배정, 쓰기/영수증/새 에이전트 재사용과 전체 목표는 유지한다.
