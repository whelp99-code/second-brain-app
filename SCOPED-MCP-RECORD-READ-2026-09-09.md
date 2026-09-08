# 범위 제한 MCP record 조회 — 실제 stdio 연결

2026-09-09 제품 `31d9ab1`. 기존 claim/분류 검증을 실제 MCP read 경로에 연결했다. 첫 연결은 `scoped-record-read-v1`이며 범위가 검증된 record 조회만 지원한다. 전체 공통 기억 운영 완료가 아니다.

## 구현과 경계

- 명시적 서버 설정 `mcp_scoped_read`의 principal/agent/session/policy revision을 claim의 값과 별도로 대조한다. 봉인된 관리형 세대와 JARVIS 공개키가 없으면 이 모드의 서버 생성을 거부한다.
- 이 연결에는 `sb_read_page` 하나만 등록한다. 기존 검색·쓰기·실행·status·resolve·최근 변경·conflict 도구를 통한 unscoped 우회 경로를 등록하지 않는다.
- 실제 요청 ID로 digest를 계산하고 서명/fence/문맥을 검증한 뒤 페이지를 조회한다. 현재 활성 세대·삭제 high-water, 정확한 커밋/원장 분류, 전체 원본 요구 범위를 함께 검사한다.
- 응답에는 profile, page ID, content digest, records, 세대/삭제 결합 정보를 담는다. 원문 전체·frontmatter는 반환하지 않는다. 이 한정된 응답을 기존 전체 page wire와 호환한다고 광고하지 않는다.
- 내부 오류와 미분류·불허 페이지는 공통 `MEMORY_SCOPED_READ_DENIED`로 반환한다. claim 누락은 MCP 입력 검증에서 거부한다.

## 검증

집중 검사: 새 scoped MCP·기존 MCP·claim **29 passed, 4.19초**. Ruff·변경 MCP 모듈 basedpyright 0 오류/0 경고. 최종 전체 `pytest -q --ignore=tests/test_embeddings.py`: **1,136 passed, 2 skipped, 208.36초**. 선택 embeddings extra 검사는 제외했으며 집중 검사와 합산하지 않는다.

실제 stdio 결과 `/var/tmp/page-access-acceptance-padlzyh0/scoped-mcp-result.json`:

- 격리 CLI 수집/수정/컴파일 → 실제 JARVIS 발급기(등록된 테스트 키·scope fixture) → 별도 Python MCP 프로세스.
- tools/list는 `sb_read_page` 하나. 올바른 claim으로 record2를 회수.
- 잘못된 page 요청, claim 누락, 서명 후 프로젝트 변조를 거부.
- 첫 MCP를 종료하고 새 프로세스로 같은 요청을 실행해 동일한 응답 확인.

## 남은 구현·보류

이 모드의 기능 축소는 아직 범위 검사를 연결하지 않은 도구를 노출하지 않기 위한 중간 단계다. 전체 목표는 유지하며 검색·쓰기·status·resolve·export·restore·context에도 같은 검사를 확장해야 한다. 기존 owner 프로필은 별도로 유지한다.

서버 문맥과 키는 시작 시 설정의 snapshot이다. 설정 변경을 실행 중 자동 반영하는 정책 갱신·철회 경로는 미구현이며, 현재는 서버 재구성이 필요하다. 이를 즉시 철회되는 운영 ACL로 주장하지 않는다. 발급기의 실제 인증 세션/정책 resolver도 아직 미연결이다.

테스트는 합성 기억·fake LLM·고정 시각·테스트 authority/범위를 사용했다. 실제 stdio 전송과 제품 코드는 실행했지만 운영 사용자 인증·전체 앱 순환·다중 사용자 OS 격리 인수로 확대하지 않는다. 원작업 계보·native 세션 사본 수명·여러 writer·검색 평가·GUI/DR 등 전체 잔여 목표를 유지한다. 운영 배포·서비스 재시작·실 vault/config 변경·push는 하지 않았다.
