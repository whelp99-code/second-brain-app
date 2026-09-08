# 제한 MCP의 권한별 lexical record 검색

2026-09-09 제품 `d561f63`. 기존 `scoped-record-read-v1`에 `sb_search`를 추가했다. 이제 제한 연결의 도구는 sb_read_page와 sb_search 두 개다. 기존 owner 검색 프로필은 유지한다.

## 구현

검색과 직접 조회가 같은 요청 서명·현재 정책·키·세대/삭제 high-water·반환 직전 만료 재검사를 거친다. 검색 서명에는 실제 query와 limit을 포함한다. limit은 1~50이다.

검색 후보를 페이지 단위로 중복 제거하고 봉인된 원본 요구 분류 전체를 검사한 뒤 record 본문에서 lexical query 일치를 확인한다. 허용된 record만 고른 뒤 limit을 적용하므로 먼저 나온 불허 결과가 허용 결과의 자리를 차지하지 않는다. 원본 FTS의 title/section/snippet/corpus score를 응답에 복사하지 않는다. 허용 record의 우선도와 안정된 ID로 순서를 결정한다.

출처 미분류·범위 불허 페이지는 건너뛴다. 손상된 세대 등 검증 실패는 검색 전체를 거부한다. 검색 결과는 page ID/content digest/record와 공통 세대 정보를 포함한다.

## 검증

최종 관련 **31 passed, 5.56초**: scoped search, scoped MCP, live policy, 기존 MCP, claim. Ruff·diff 통과, 변경 모듈 basedpyright 0 오류/0 경고.

- 허용/불허/미분류 세 원본에 같은 검색어를 넣어 limit1에서도 허용 자료만 반환되는지 검사했다. 불허어 검색과 다른 소유자 검색은 빈 결과다.
- MCP에서 검색어와 limit에 결합된 claim을 검증하고, limit 변경 시 거부했다. 기존 조회 중 철회·만료 회귀도 유지한다.
- 실제 `/var/tmp/page-access-acceptance-fqfklvky/scoped-mcp-result.json`: JARVIS 실제 issuer로 sb_search 요청을 발급해 별도 stdio MCP에서 검색 record2를 회수했다. 서명된 limit 변경은 거부했다. 같은 연결의 정책/키 변경 거부·복원과 새 프로세스 재실행도 통과했다.
- 기본 fake LLM은 원문이 아닌 `Cited.`를 생성한다. 실제 stdio 검사는 이 결정적 텍스트를 검색한다. 분리 범위 테스트는 원문을 인용한 결정적 fixture LLM을 사용했다. 실제 LLM 품질 검사가 아니다.

초기 검색 실패는 fake 출력과 원문 검색어가 다른 점, 여러 root 수집 결손, fixture가 후속 conflict 프롬프트를 처리하지 못한 점을 구분해 조사했다. 최종 통과 수치에 실패 실행을 합산하지 않는다. 전체 회귀를 이번 실행으로 주장하지 않는다.

## 새로 확인한 P0 수집 결손

현재 registry는 adapter 종류당 한 번만 create(config)하고 markdown connector는 첫 설정 root를 선택한다. 같은 adapter의 세 source를 한 번에 지정한 실제 수집에서 원장에 첫 source 한 개만 기록됨을 확인했다. 여러 에이전트/프로젝트 원본을 설정만 추가해 모두 수집된다고 판정할 수 없다.

이번 권한 검색 검증은 명시적 source별 수집을 각각 실행하여 세 원본을 같은 원장에 넣었다. 이는 검색 검증을 위한 현재 지원 경로이며 배치 수집 결함 수정의 대체가 아니다. 다음 P0는 registry 파일을 수정하지 않고 pipeline의 configured source 인스턴스 선택을 보강하여 각 root/cursor/분류가 독립적으로 처리되는지 검증하는 것이다. 다중 root 배치 수집 완료 선언은 보류한다.

## 잔여 목표와 제한

첫 검색은 lexical이다. semantic/hybrid의 같은 범위 검사는 아직 연결하지 않았다. 검색 후보 전체를 검사하므로 큰 자료 집합의 지연·메모리/응답 예산을 실측해야 한다. 이번 작은 fixture 결과를 운영 성능 인수로 확대하지 않는다.

운영 권한 resolver, 쓰기/status/resolve/export/restore/context, 원작업 계보·native 세션 사본·실제 앱 순환·여러 writer·검색 품질·GUI/DR의 전체 목표를 유지한다. 실제 인수는 격리 authority/키/범위/시각과 합성 기억을 사용했다. 운영 배포·서비스 재시작·실 vault/config 변경·push는 수행하지 않았다.
