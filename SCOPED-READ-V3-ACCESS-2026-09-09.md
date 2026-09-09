# 공통 기억의 정확한 접근 분류를 확인하는 scoped read v3

인계 방향인 세컨드브레인 기반 유지와 OSS 장점 선별 흡수를 유지한다. 이번 변경은 자비스와 여러 에이전트의 저장 결과 검증에서 남았던 접근 분류 증거를 연결하는 M2/M3/M7/M12 작업이다.

## 변경과 동작

기존 scoped read v1/v2 계약 파일을 바꾸지 않고 `scoped-record-read-v3`를 추가했다. 도구는 v2와 같은 읽기 전용 3개이며 새 쓰기 도구를 노출하지 않는다. v3의 `sb_read_page`만 `page_access`를 추가한다. 검색과 상태 응답에는 분류를 넣지 않는다.

세컨드브레인은 같은 pinned generation에서 원문과 ledger를 검증하고 현재 scope를 통과한 후, 모든 출처의 분류를 반환한다. 표시된 인용에 등장한 출처만 선택하는 것이 아니다. 출처 식별 해시, owner/projects/policy revision, 기존 source_access 분류 해시를 함께 제공하며 최대 64개로 제한한다. 범위를 넘거나 분류가 불완전하면 실패한다. 응답 생성 전후의 현재 정책·키·삭제 high-water·read fence 검사는 유지한다.

자비스는 v3 계약 파일의 고정 체크섬, 실제 도구 스키마, 응답 프로필, 현재 요청과 claim, 세대/삭제 fence를 대조한다. 페이지 분류는 필수이고, 형식·순서·중복·owner·projects·policy·해시를 검사한다. `readRememberedArtifact`는 원래 요청의 단일 출처 식별자와 정확한 분류까지 일치할 때 `remembered_artifact_observed`를 반환한다. v1/v2의 `remembered_content_observed`와 구분한다. 본문이 같고 다른 프로젝트가 현재 읽기 권한에 포함되더라도 저장 분류가 원래 요청과 다르면 성공하지 않는다.

`createProductionScopedMemory`에 명시적인 v3 선택 옵션을 추가했다. 기본값은 v2이며 자동 전환은 하지 않는다. 전화 gateway에서 v3를 명시한 경우 capabilities도 해당 구성값을 보고하도록 연결했다. configured/readiness는 구분되며, 설정만으로 정상 동작을 주장하지 않는다.

## 검증과 실패 이력

- SB scoped MCP 검사 6개 통과. v1/v2 응답 불변, v3 분류 반환, 실제 도구 스키마 일치, 서명/권한/세션/철회 검사 포함. 새 projection의 빈 출처·64개 초과 거절 회귀 추가.
- 최종 SB 전체 회귀는 **1,241 통과/2 건너뜀, 224.67초**다. 명령: `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`. 선택적 embeddings 테스트는 제외했다. Ruff와 새 모듈 basedpyright(오류 0/경고 0)는 통과했다.
- JARVIS 최종 관련 74개/18.16초 통과. 8개 파일의 transport/profile/production/client/phone 검사다. TypeScript 격리 emit, 변경 파일 ESLint 통과. 운영 dist는 빌드하지 않았다.
- 분류를 제거하거나 불완전으로 바꾸는 경우, 중복/추가 필드, 해시를 다시 계산한 출처·프로젝트·owner·policy 변경, 여러 출처 혼합을 거절했다. 서로 다른 버전의 계약 파일을 잘못 지정하면 거절한다.
- 실제 v3 실행 첫 시도에서 테스트 정책의 methods 정렬 오류가 검출돼 fixture를 수정했다. 다음에는 v3가 빠진 frozen schema 비교 분기로 handshake가 실패했다. 이를 단위 테스트 1 실패/4 통과로 재현하고 분기를 연결했으며, 관련 9개 검사와 최종 74개 검사를 통과했다. 진단 파일 부재 처리 및 Ruff import 정렬 오류도 수정했다. 실패를 성공으로 집계하지 않는다.
- [실제 프로세스 인수 결과](SCOPED-READ-V3-ACCESS-2026-09-09.json): production 구성 함수·파일 정책·기존 issuer·supervised stdio MCP로 v4 저장소의 4개 레코드와 정확한 분류를 읽었다. MCP 재시작, 여러 프로젝트가 허용된 reader의 범위 포함 조회, provider 정책 변경 거절, issuer 정책 철회를 확인했다. 별도 v2 실행도 기존 결과 형식으로 성공했다.
- 별도 임시 패키징 디렉터리에서 copy-migrations.mjs를 실행해 v1/v2/v3 계약과 checksum이 원본과 동일하게 복사됨을 확인했다. v3 SHA-256: `c3d4b1d883d8966fcc39b5f26e999159cb60977c248683d5719da27fd5500ad8`.

실행은 격리 DB/저장소, 고정 시계, 테스트 키·세션을 사용했다. 초기 v4 쓰기의 authority callback은 fixture=True다. 실제 제품 코드·프로세스 경로를 검증한 것이며 운영 사용자의 권한 설정이나 배포 인수 완료를 의미하지 않는다.

## 남은 완료 조건과 보류

정확한 현재 분류를 관찰하는 선행 조건은 구현했다. 이 관찰만으로 과거 provider proof의 진위나 특정 outbox의 최종 상태를 바꾸지 않는다. 자동 settled/control completed는 계속 보류하며, 현재 관찰·원래 수락·provider 완료 증거를 현재 정책/삭제 fence와 함께 durable 상태 전이에 결합해야 한다.

운영 v4 권한 검증기, 공개 dispatch/status 계약, 여러 worker/reader 버전의 배포 검증, 실제 에이전트 운영 인수와 전체 M1–M14는 남아 있다. v3를 쓰려면 새 provider와 새 자비스 계약/소비자를 함께 사용해야 하며, 구버전으로의 fallback은 허용하지 않는다. 이번 작업에서 운영 배포·서비스 재시작·데이터 변경·push는 수행하지 않았다.
