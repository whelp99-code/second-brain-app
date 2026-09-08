# 빈 검색 결과의 세대 결손 수정

2026-09-09. JARVIS `cec7943`, SB 인수 `158bd75`. [실측 JSON](SCOPED-EMPTY-GENERATION-2026-09-09.json).

scoped 문맥 연결부는 빈 검색을 no_data로 변환하면서 응답 generation을 버렸다. 검색 전후 status가 G1인데 검색 자체가 G2의 빈 결과여도, record가 없어 개별 generation 검사도 수행하지 못했다. 수정 전 회귀에서 이 경우 714바이트 empty 문맥이 반환되는 것을 재현했다.

내부 no_data 결과에 선택적 generation 필드를 추가하고 scoped 연결부는 실제 검증된 응답의 generation을 반드시 전달한다. 기존 reader는 이 값이 있으면 검색 후 status와 대조하여 다르면 `MEMORY_REFERENCE_GENERATION_CHANGED`로 거부한다. 기존 비-scoped 결과 계약을 강제 변경하지 않고, public memory-reference-v1 payload에 임의 metadata를 추가하지 않는다.

검증 결과:

- 수정 전 신규 회귀 1개 실패, 수정 후 관련 reference/submit/context/scoped 71 passed / 4 files / 28.69초.
- TypeScript 격리 emit, ESLint, diff 통과.
- 실제 MCP 정상 빈 검색은 empty로 처리됐다. 인수 도구가 그 응답의 generation_id만 바꾼 경우 reader가 거부했다. 이는 응답 대체 시나리오이며 운영 provider의 실제 세대 역행을 발생시킨 시험은 아니다.
- 기존 record 2개/4,412바이트 문맥 준비·제출, 중복 제출과 쿠키 제거 거부, v1/v2 조회 및 응답 직후 정책 철회도 재인수 통과했다.

실제 결과: `/var/tmp/page-access-acceptance-y393waoc/scoped-mcp-result.json`. 테스트 owner/key·합성 원본·fake compiler·고정 시각을 사용한다. 전체 SB 스위트를 이번에 재실행하지 않았다.

CLI/HTTP 인증 진입점, 모델/native 세션의 수신·보존·삭제, scoped 쓰기·resolve·복구 및 기존 전체 운영 인수 목표는 남는다. 기존 일반 owner CLI의 프로필을 자동 전환하거나 배포하지 않았다.
