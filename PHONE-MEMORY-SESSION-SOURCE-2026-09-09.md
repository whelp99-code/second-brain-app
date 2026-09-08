# 기존 세션 인증과 범위 기억 연결부 — 2026-09-09

JARVIS `7ae0684`, SB 인수 `7a675d0`. [실측 JSON](PHONE-MEMORY-SESSION-SOURCE-2026-09-09.json).

## 기존 인증 대조

`dashboard/session.ts`의 authenticatedSessionId는 프로세스에서 생성한 식별자다. CSRF 검사와 함께 쓰이지만 agent별 로그인·프로젝트·만료 정보를 제공하지 않는다. 이 값을 곧바로 기억용 인증 세션으로 사용하는 방법은 보류했다.

`dashboard/phone-session.ts`는 기존 게이트웨이가 사용 중인 쿠키 HMAC·소유자 일치·idle/absolute 만료 검증을 제공한다. 새 세션 저장소나 인증 DB를 만들지 않고 이 검증을 재사용했다.

## 구현

- 인증 성공 결과에 현재 idle/absolute 중 이른 expiresAt을 제공한다. 읽기는 lastSeenAt을 갱신하지 않는다.
- 기존 성공 결과는 저장된 idHmac/csrfHmac Buffer 자체를 노출했다. 호출자가 수정하면 내부 세션 identity/CSRF까지 바뀌는 결손을 수정해 복사본을 반환한다. 회귀에서는 결과 buffer를 덮어쓴 뒤에도 다음 인증과 원래 CSRF 검사가 유지됐다.
- `dashboard/memory-session-source.ts`는 매 호출 현재 쿠키와 현재 owner digest를 기존 store에 다시 인증한다. 세션 HMAC에서 별도 domain hash로 `session:phone:<digest>`를 만들고, 원 쿠키나 CSRF는 기억 claim에 넣지 않는다.
- agent ID는 신뢰된 서버 설정에서 받아야 한다. 입력 body의 agent/session/project를 인증으로 사용하지 않는다. 연결부는 owner principal/agent/session/expiry만 반환하고 프로젝트 권한은 기존 파일 정책에서 별도로 검사한다.
- idle 정확한 경계 시점에는 기억 공급자가 거부한다. 기존 gateway authenticate는 idle 경계 +1ms부터 거부하는 동작을 유지하되, 만료 시각까지 새 기억 claim을 발급하지 않는다.

## 검증

게이트웨이·세션·기억 프록시 및 새 공급자 회귀: **50 passed / 5 files / 1.19초**. 잘못된 owner, 쿠키 누락, idle 만료, 반복 조회의 만료 연장 없음, buffer 수정 격리를 확인했다. TypeScript 격리 emit 및 변경 TS ESLint·diff 통과.

실제 격리 인수: `/var/tmp/page-access-acceptance-jk_8aa9c/scoped-mcp-result.json`.
기존 store에서 쿠키를 발급하고 새 공급자가 인증한 세션 ID를 격리된 provider 설정과 파일 정책에 명시했다. issuer→기존 supervised transport→별도 Python MCP→scoped client로 페이지·검색 각 1개 그룹을 회수했다. 쿠키를 제거하면 다음 조회는 발급 단계에서 거부됐다. 실제 응답 뒤 정책 철회에 대한 반환 차단도 반복 확인했다.

실제 HTTP 로그인 요청이나 운영 Tailnet 인증을 실행한 것은 아니다. 테스트 owner/key·합성 원본·fake compiler·고정 시각의 격리 인수다. 쿠키를 직접 발급한 store 사용과 운영 로그인 인수를 구분한다.

## 다음 연결 및 보류

현재 `phone-gateway-adapter.ts`는 백엔드 `/api/v1/session`에서 공통 CSRF 토큰을 받은 뒤 새 요청 ID/Host/Origin으로 기억 요청을 프록시한다. 휴대폰 쿠키의 검증된 session identity를 백엔드에 전달하는 계약은 없다. 새 공급자가 있다는 이유로 이 HTTP 경계가 완성됐다고 판단하지 않는다.

후속 작업은 기존 게이트웨이와 백엔드의 신뢰 경계에서 인증된 세션을 전달하는 방법, 새 세션에 대한 운영 project 정책 배정, provider의 세션별 연결 구성이다. 공통 CSRF만으로 에이전트 권한을 추론하거나 임의 HTTP 헤더를 신뢰하는 경로는 보류한다. 승인되지 않은 프로젝트 범위를 자동 배정하지 않는다.

모델/native 세션 전달·보존·정정/삭제, scoped 쓰기/status/resolve/restore 및 M2~M14와 전체 운영 인수 목표는 유지한다. 운영 서비스·설정·DB·dist를 변경하거나 푸시/배포하지 않았다.
