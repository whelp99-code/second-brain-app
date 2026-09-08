# 명시적 에이전트 정책과 새 로그인 기억 사용

2026-09-09. JARVIS `d020bc4`, SB `e95fa8f`.

## 해결한 연결 결손

기존 정책 v1은 session ID를 미리 등록하고 provider도 그 세션에 고정했다. 새 로그인마다 두 설정을 수정해야 했으며 실제 인수 helper도 시험 운영자 역할로 세션을 등록했다. 이제 선택적 에이전트 정책 v2와 provider의 명시적 issuer_authenticated 모드를 함께 사용하면, 등록된 에이전트의 현재 인증 세션들이 같은 명시적 프로젝트 범위를 사용할 수 있다. 새 로그인에 대한 정책 파일 쓰기·키 발급·별도 DB를 추가하지 않는다.

JARVIS 정책 v1의 sessions 행은 그대로 정확히 일치해야 한다. v2는 sessions 대신 agents 행에 agent_id/projects/methods를 명시한다. 두 형식을 혼합하거나 자동 전환하지 않는다. 현재 서버 인증 공급자의 principal/agent/session/expiry를 먼저 검사하고 현재 파일의 허용 agent/method/project를 적용한다. 인증 공급자가 없거나 agent 미등록·만료·철회·중복/손상 정책이면 거부한다. 발급 claim에는 각각의 실제 session ID를 계속 넣는다. 정책 캐시나 wildcard project를 추가하지 않는다.

provider 설정은 기존 session 필드 대신 아래를 명시적으로 선택한다.

```toml
[mcp_scoped_read]
principal = "principal:owner"
agent = "agent:test"
session_mode = "issuer_authenticated"
policy_revision = "policy:1"
```

이 모드는 scoped-record-read-v2 전송 프로필에서만 허용한다. session과 session_mode를 동시에 지정하거나 알 수 없는 모드를 넣으면 거부한다. 열린 연결에서 고정↔issuer 모드를 바꾸면 재연결이 필요하다. 기존 session 모드 및 scoped v1은 그대로 유지한다.

이 설정은 JARVIS의 기존 신뢰 signer가 인증한 세션을 신뢰한다는 명시적 결정이다. claim의 session 값을 복사해 자기 자신과 비교하지 않는다. 대신 형식이 유효한 session ID의 서명을 기존 키로 검증하며 provider/principal/agent/policy revision/purpose/request, 현재 fence와 만료/삭제 high-water를 계속 검사한다. 서명 없는 session 변조, 다른 agent·project·정책과 만료/키 철회는 허용되지 않는다. claim/fence 서명 wire 버전이나 frozen MCP tool schema는 변경하지 않았다.

## 검증

- JARVIS 정책·scoped production·scoped client: **8 passed / 3 files / 4.97초**. 세션별 v1 유지, 두 인증 session ID 유지, 미등록 agent/인증 누락/만료/철회/프로젝트 변경 및 혼합·중복·wildcard 거부.
- SB claim·현재 정책·MCP·scoped 검색: **23 passed / 5.62초**. 고정 세션 거부, 명시 모드의 서명된 다른 세션 수락, 미서명 변조/다른 agent/project 거부, v1에서 새 모드 거부 및 기존 철회/만료 검사.
- TypeScript 격리 emit·변경 파일 ESLint, 전체 sb/tests Ruff·diff·JS 구문 통과. Python 변경 claim/policy 정적 검사 **0 errors / 0 warnings / 0 notes**.
- 초기 잘못된 pytest 파일명 실행은 수집 전 실패했으며 올바른 파일로 위 검사를 실행했다. JARVIS 테스트의 미사용 변수 lint 2건은 수정 후 통과했다.

실제 HTTP/MCP 인수:

1. 기존 v1에서는 새 로그인 세션의 조회를 403으로 거부했다.
2. 시험 운영자가 에이전트 정책 v2와 issuer mode를 한 번 설정했다.
3. 앞서 발급한 미등록 로그인과 설정 후 새로 발급한 로그인에서 각각 기억 **2개**를 회수했다. 두 조회 사이 정책/provider 파일 내용이 바뀌지 않았음을 비교했다.
4. agent 허용 행을 제거하자 동일 로그인에서 403으로 거부했다.
5. 기존 고정 설정으로 돌려 v1의 정책 철회, 잘못된 입력400, MCP 종료 중 세션 만료401 및 쿠키 제거를 재검증했다. 기존 CLI·v1/v2·응답 변조·독립 프로세스 중복 제출 인수도 유지했다.

[결과 JSON](AGENT-POLICY-LOGIN-2026-09-09.json), 원본 `/var/tmp/page-access-acceptance-fuchw58p/scoped-mcp-result.json`. 재현: `TMPDIR=/var/tmp uv run python scripts/scoped-mcp-acceptance.py <격리 JARVIS 빌드 경로>`.

## 운영 적용 조건과 남은 범위

실제 gateway 쿠키와 MCP를 사용했지만 Tailnet 신원 헤더·owner/key·정책·원본·시각은 fixture이고 compiler는 fake다. 운영 Tailnet 접속·실제 데이터 인수로 표시하지 않는다. 운영 서비스를 수정하거나 배포/재시작하지 않았다. 이전 전체 Python 1,142통과 수치는 이번 변경 전 기록이며 이번 현재 전체 통과 수치로 재표기하지 않는다.

v2 agents 정책은 해당 agent의 유효한 인증 세션 전체를 대상으로 한다. 특정 로그인만 허용해야 하는 경우 v1을 사용한다. 특정 세션의 인증 철회는 인증 공급자가 담당하며 v2 정책에서 agent를 제거하면 그 agent의 세션 전체가 거부된다. 같은 OS 권한을 공유하는 프로세스의 파일 접근 격리나 다른 사용자의 인증 체계를 새로 제공하는 기능은 아니다.

이 단위로 로그인별 수동 정책 작성의 결손을 닫았지만 운영 활성화·준비 상태·요청 취소 정리, scoped 저장→검증된 작업 결과→영수증→다른 에이전트 재사용, 정책 rollback·정정/삭제·모델 로그/복구 및 전체 M1~M14 인수는 남는다. 기본 정책을 자동 변환하지 않고 선택적 모드로 제공한다.
