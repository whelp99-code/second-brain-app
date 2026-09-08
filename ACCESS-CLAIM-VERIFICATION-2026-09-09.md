# 범위 claim 검증 계약과 실제 프로세스 인수

2026-09-09 제품 `d220902`. 이전 단계의 내부 범위 판정에 요청·세션·정책·읽기 fence를 결합하는 claim 검증을 추가했다. 전체 운영 완료가 아니다.

## 변경

- `MemoryAccessClaimV1`: 별도 서명 domain `orca-jarvis/memory-access-claim/v1`의 닫힌 모델. provider, principal, agent/session, 정렬된 project 집합, policy revision, purpose, 실제 요청 digest, 읽기 fence digest, 발급/만료, nonce, key ID를 서명한다.
- `AccessContext`는 claim에서 되읽어 만드는 값이 아니라 서버·인증 세션·현재 정책의 기대값이어야 한다. 요청 digest는 실제 method와 검증된 의미 인자로 계산하며 target/filter/pagination/budget을 포함해야 한다.
- 기존 Ed25519 검증과 현재 신뢰 공개키 집합을 재사용한다. 읽기 fence의 서명·목적·현재 삭제 high-water·시간도 재검증한다. claim은 fence 유효 기간 안에서만 유효하며 최대5분이다.
- `require_claimed_page`는 검증된 범위를 페이지 전체 원본 분류와 대조한다. 페이지의 provider·삭제 sequence/root가 현재 문맥과 맞아야 하며 status/resolve 목적을 페이지 읽기 허용으로 쓰지 않는다.
- 봉인 page bundle에 검증된 manifest의 삭제 sequence/root를 추가했다. 현재 claim을 과거 삭제 상태 페이지에 붙여 사용하는 것을 거부한다.

## 검증

최종 관련 **43 passed, 7.33초**: access_claims, memory_access, page_access, delegations, source_access, task32 schema4 integration. Ruff·diff 통과, 변경 제품 모듈 basedpyright **0 오류/0 경고**, Node syntax 통과. 이전 전체 검사와 합산하거나 이번 전체 검사로 재표기하지 않는다.

검사에는 정상 서명, 다른 provider/principal/agent/session/policy/purpose/request/fence, 잘못된 project 집합, 유효 기간 초과·만료, 서명 후 변조, 키 제거, 오래된 high-water, 페이지 분류 불일치와 다른 페이지 세대 삭제 상태를 포함했다.

실제 프로세스 결과: `/var/tmp/page-access-acceptance-r3phrz2h/access-claim-result.json`.

1. 격리 실제 CLI 수집·컴파일·수정·재컴파일로 요구 원본2/record2인 봉인 페이지를 만들었다.
2. 별도 Node 프로세스의 테스트 Ed25519 키로 claim을 서명했다.
3. Python 검증기가 서명·fence·기대 요청 문맥과 실제 페이지 분류를 함께 대조해 통과했다.
4. 서명 후 project 변경은 거부했다.

테스트 키·합성 문맥·fake LLM을 사용했다. Node 스크립트는 JARVIS 운영 권한 발급자가 아니며, 사용자 신원을 검증했다고 주장하지 않는다. 실제 MCP 전송 계약은 변경하지 않았다.

## 보류와 남은 구현

- 외부 요청에서 AccessContext를 그대로 채우는 방식은 보류한다. claim의 서명이 있어도 발급자가 허용 범위를 확인하지 않으면 권한 검사가 완성되지 않는다. 다음은 JARVIS의 검증된 작업/사용자 문맥·현재 정책·키 수명에서 발급하는 경로다.
- 현재 read fence v1의 principal:owner 제한을 그대로 대조한다. 같은 소유자의 여러 agent/project만 첫 범위 모델로 다룬다. 다중 사용자 확대는 양쪽 fence 계약 버전 변경과 전체 표면 인수까지 보류한다.
- 조회용 claim은 쓰기 권한이 아니다. 쓰기 요청/승인 digest와 분류의 결합, status/resolve/export/restore/context 전체 검사, 새 MCP profile과 양쪽 호환 검증이 남는다.
- 키의 현재 허용 목록과 시점별 유효 정책은 호출자의 신뢰 저장소에서 공급해야 한다. 이번 키 제거 검사를 전체 운영 키 수명 인수로 확대하지 않는다.
- 이전 범위·원작업 계보·native 세션/백업·실제 자비스 앱 사용 순환·여러 writer 배제·검색/GUI/복구 목표를 유지한다.

운영 배포·서비스 재시작·vault/config 변경·push는 수행하지 않았다.
