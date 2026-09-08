# 자비스 파일 기반 범위 공급자

2026-09-09 JARVIS 제품 `623ef50`, SB 실제 연결 인수 `79ede52`.

## 구현

`createFileMemoryAccessScopeResolver(policyPath, provider, getSession)`는 기존 claim 발급기의 범위 공급 포트에 연결한다. getSession은 인증된 서버 상태를 공급해야 하며 HTTP/MCP 요청 본문에서 값을 복사하는 함수가 아니다. 세션 ID만으로 권한을 부여하지 않고 현재 정책 파일의 정확한 agent/session 항목과 일치해야 한다.

정책은 schema_version, provider_instance_id, principal_id, policy_revision, valid_from, valid_until, sessions를 가진다. sessions 각 항목은 agent_id, session_id, projects, methods를 가진다. 첫 모델은 principal:owner이며 methods는 sb_read_page/sb_search만 허용한다. 알 수 없는 필드, 중복 session/grant/project, 유효하지 않은 날짜와 scope는 거부한다. 반환 유효 기간은 정책과 인증 세션 만료 중 빠른 시점이다.

파일은 매 요청 새로 읽는다. 절대 경로의 소유자 전용 일반 파일·단일 링크·현재 OS 사용자 소유·최대64KiB를 요구한다. symlink를 따르지 않고 nonblocking으로 열며, 읽기 전후 파일 metadata와 경로 identity를 대조한다. 기존 bounded strict JSON parser를 재사용한다. 파일 누락·손상·허용 범위 철회 때 이전 성공 결과를 캐시해 반환하지 않는다. 키 생성·등록·새 권한 DB나 승인 UI를 추가하지 않았다.

## 검증

- JARVIS 직렬 테스트 **21 passed, 13.97초**: 새 파일 정책, 실제 claim issuer, 기존 read-fence production.
- 현재 session/project/method/provider/정책 및 세션 만료, 파일 변경/삭제/손상/중복 키/불안전 권한/symlink 거부를 확인했다.
- 변경 파일 ESLint, TypeScript 격리 emit(타입 검사 포함), Node syntax, diff 검사 통과.
- 실제 `/var/tmp/page-access-acceptance-kqgnpxd2/scoped-mcp-result.json`: 제품 파일 정책 공급자 → 현재 DB 키를 검사하는 실제 JARVIS issuer → Python stdio MCP 직접 조회·검색. record2 회수와 서명 변경 거부, provider 정책 변경/복원 및 재시작 반복 인수를 유지했다.
- 발급 스크립트는 정책 sessions를 비운 뒤 다음 issue가 MEMORY_ACCESS_SCOPE_UNAVAILABLE로 실패하는 것도 실제 코드에서 확인했다.

정책 파일·인증 세션 getter·authority DB·키·기억·시각은 격리 fixture다. 파일 파싱·대조·발급·MCP 전송은 제품 코드로 실행했다. 실제 앱의 사용자가 인증됐다는 증거로 확대하지 않는다.

## 정책 형식 예시와 사용 경계

```json
{
  "schema_version": 1,
  "provider_instance_id": "provider:second-brain:linux",
  "principal_id": "principal:owner",
  "policy_revision": "policy:1",
  "valid_from": "2026-09-09T00:00:00.000Z",
  "valid_until": "2026-09-10T00:00:00.000Z",
  "sessions": [{"agent_id":"agent:jarvis","session_id":"session:verified-session","projects":["project:alpha"],"methods":["sb_read_page","sb_search"]}]
}
```

예시를 운영 파일에 설치하지 않았다. 실제 session ID·만료는 서버 인증 문맥에서 가져오고, 정책은 운영자가 관리하는 경로에서 읽어야 한다. 파일 정책을 사용자 요청의 project 문자열로 자동 생성하는 경로는 보류한다.

## 잔여 목표

새 공급자는 정책 파일 대조 부분을 구현했다. 앱/CLI의 인증 세션 getter 연결, 제한 연결을 실제 자비스 adapter에서 사용하는 설정·응답 검증·문맥 전달은 남는다. 기존 owner 프로필을 조용히 대체하지 않았다.

정책 철회는 다음 발급을 막는다. 이미 발급된 claim의 즉시 전역 철회는 별도 provider 정책/키 갱신과 수명 계약이 필요하며 이 테스트로 완료를 주장하지 않는다. 정책 rollback/복구도 별도 인수가 남는다.

쓰기/status/resolve/export/restore/context 전체 범위, 원작업 계보·native 세션 사본·실제 앱·여러 writer·검색 성능/품질·GUI/DR의 전체 목표를 유지한다. 운영 배포·서비스 재시작·실 vault/config 변경·push는 수행하지 않았다.
