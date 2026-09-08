# 범위가 적용된 세대 상태 조회 — 2026-09-09

JARVIS `29c26f1`, SB `ab0776f`. [실측 JSON](SCOPED-GENERATION-STATUS-2026-09-09.json).

## 계약과 구현

기존 문맥 공급기가 사용하는 조회 전후 상태 검사의 선행 기능을 구현했다. 기존 `scoped-record-read-v1`의 두 도구와 고정 계약은 유지하고 `scoped-record-read-v2`에 `sb_generation_status`를 추가했다. v2는 status/read/search 세 도구다. JSON/sidecar의 고정 SHA-256은 `a5af30045ba19eb6e79d07f649e3049842741822d75bdb7212d2ec7eabd9cb37`이다.

서버 stdio는 `SB_MCP_CONTRACT_PROFILE=scoped-record-read-v2`와 기존 `mcp_scoped_read` 설정을 요구한다. 상태 요청의 method/빈 semantic arguments digest, 목적 `memory_status`의 claim과 status fence, 현재 세션/정책/키/삭제 이력을 대조한다. 읽기용 claim은 상태 요청에 사용할 수 없다. 기존 generation pin과 활성 세대·삭제 high-water 검사 및 조회 전후 현재 정책 검사를 재사용한다.

상태 응답은 profile/request/claim digest, 세대 metadata, schema_version=1, pointer_health/journal_health를 포함하며 원문·record·원본 경로를 포함하지 않는다. 검증된 활성 상태만 healthy로 반환하며 이상 상태에서 정상으로 가장해 반환하지 않는다. 모든 도구·원장·운영 서비스의 가용성을 종합 진단한다는 의미는 아니다.

자비스 issuer는 명시적 `memory_status` 목적을 받을 수 있고 status 메서드와 목적을 대조한다. 파일 정책의 methods에 `sb_generation_status`가 있어야 한다. `createMemoryScopedClient`는 v2와 별도 status issuer가 있을 때 `status()`를 제공하고 발급·전송 전·반환 전 현재 권한 검사를 유지한다. 소비자는 healthy 상태의 닫힌 필드 집합, status 목적 fence, 요청/claim/삭제 metadata를 검사한다.

기존 metadata 검증 로직을 재사용하기 위해 status 응답의 세대 필드 검사는 record-read와 같은 binder를 사용한다. record를 만들어 넣거나 본문 검사로 상태 권한을 대신하지 않는다.

## 검증

- JARVIS 전송/기존 프로필/새 v2/issuer/파일 정책/소비자 회귀: **102 passed / 14 files / 11.00초**.
- SB v1/v2 실제 서버 계약, 상태 권한 목적 거부 및 claim/기존 프로필 호환: **23 passed / 4.90초**.
- Ruff sb/tests, 변경 SB 모듈 basedpyright 0 errors/0 warnings, JARVIS ESLint 및 격리 emit 통과.
- 실제 패키징 스크립트: 새 격리 디렉터리에 계약 JSON 6개와 sidecar를 복사하고 원본 bytes/digest 일치 확인.
- 실제 v2 인수: phone 세션 저장소 인증→현재 파일 정책→issuer→기본 launcher→별도 Python MCP→status→page/search→status. 전후 및 검색 세대가 일치했다. 쿠키 누락과 실제 응답 직후 정책 철회도 거부했다.
- 기존 v1 경로도 같은 인수에서 반복 통과했다. JSON의 v1 `status_before_after_equal=false`는 v1에서 상태 조회를 수행하지 않았다는 뜻이며 실패가 아니다.

실제 결과 `/var/tmp/page-access-acceptance-7uazzrwc/scoped-mcp-result.json`, 패키징 `/var/tmp/scoped-v2-package-7nodmwfz/result.json`.
테스트 owner/key·고정 시각·합성 원본·fake compiler를 사용했다. 운영 HTTP 로그인·실제 모델 세션 인수 및 배포는 수행하지 않았다. 이번 변경 뒤 전체 SB 스위트를 다시 실행하지 않았으며 이전 전체 1,141 passed/2 skipped는 `0b969d7` 시점이다.

## 남은 연결

상태 조회 선행 기능은 실제 전송까지 검증했다. 기존 `MemoryReferenceReader`의 `SecondBrainReadAdapter` 결과/상태 형태와 새 클라이언트를 연결하고 privacy/삭제/분량 검사를 유지하는 제품 통합은 남는다. HTTP 게이트웨이→백엔드 인증 세션 전달, 프로젝트 정책 배정, native 세션 수명, scoped 쓰기/resolve/복구 및 전체 M2~M14 목표를 유지한다. 일반 adapter의 프로필 일괄 전환과 CSRF의 agent 권한 재해석은 계속 보류한다.
