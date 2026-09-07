# 검색어 어순과 MCP 근거 선택 개선

## 구현 결과와 병합 상태

기존 trigram 검색을 재사용하면서 공백으로 나눈 모든 검색어가 있는 자료를 어순과 관계없이 찾도록 구현했다. 봉인 검색·비봉인 검색·MCP record 선택이 같은 `sb/search_query.py:LexicalQuery`를 사용한다. 검색 인덱스 schema, generation binding, read fence, record ID/digest, 원문 저장과 MCP 필드는 변경하지 않았다.

원 작업공간에서 실행 중인 100회 쓰기 인수가 제품 hash를 고정하므로, 구현과 검증은 `/var/tmp/sb-korean-query-work`의 `codex/korean-query-consistency-20260908`에서 진행한다. 해당 인수가 끝날 때까지 원 작업공간으로 병합하지 않는다. 운영 서비스에 배포하지 않았다. 구현 전 결정은 [질의 ADR](LEXICAL-QUERY-ADR-2026-09-08.md), 기존 기준선은 [100개 질문 평가](KOREAN-SEARCH-BASELINE-2026-09-08.md)다.

## 동작

- `배포 오로라` → `오로라 배포는 ...`, `v2.4.1 오로라` → 두 값이 있는 자료를 회수한다. 여러 검색어는 AND 조건이며 `OR` 같은 입력도 연산자가 아닌 문자 값이다.
- 3자 이상은 기존 FTS trigram에 인용된 값으로 전달하고, 짧은 한글/영문은 기존 substring 조건을 AND로 결합한다. 경로/제목/section 검색은 기존 CLI의 후보 검색 의미를 유지한다.
- 전체 입력 문구가 연속으로 있는 후보 페이지를 먼저 정렬하고 이후 BM25와 기존 동점 순서를 적용한다. 선택한 페이지 안에서도 연속 문구가 있는 record를 먼저 고른다. 모든 페이지의 record를 재수집해 전역 rerank하는 기능은 아니다.
- MCP schema 4/5는 모든 검색어가 **같은 인용 record**에 있는 경우만 반환한다. 제목에만 있거나 서로 다른 record에 단어가 나뉜 후보는 슬롯을 소비하지 않는다. 기존 dedup과 record 선택 후 limit을 유지한다.
- 조회 과정의 DB/봉인 파일 쓰기, 추가 외부 모델·그래프 서비스·벡터 모델을 도입하지 않았다.

## 고정 질문의 실제 CLI/MCP 전후 비교

같은 dataset SHA-256 `8f82e7f1b431766c2a39e018055daa56dcd9430fd67a572c07065f6c1e9d3c55`를 사용했다. CLI와 MCP의 지표는 같다.

| 지표 | 이전 | 개선 후 |
|---|---:|---:|
| 정답 있는 질문 수 | 90 | 90 |
| 정답 문서 Recall@5 | 40/90, 44.44% | 60/90, 66.67% |
| Hit@1 | 38/90, 42.22% | 59/90, 65.56% |
| MRR@5 | 0.4333 | 0.6611 |
| 정확한 문구 Recall@5 | 20/20 | 20/20 |
| 키워드 Recall@5 | 20/20 | 20/20 |
| 어순 변경 Recall@5 | 0/20 | 20/20 |
| 자연어 질문 Recall@5 | 0/20 | 0/20 |
| 의역 Recall@5 | 0/10 | 0/10 |
| 정답 없는 질문의 빈 결과 | 10/10 | 10/10 |

회수한 근거에 대한 MCP search/read record ID·digest·출처 identity·7개 generation binding 64건 대조, 정답 span 60건 대조, 봉인 파일 불변을 확인했다. 이 fixture는 인용 페이지를 직접 작성하며 ingestion/LLM 생성·실제 앱 자동 주입을 평가하지 않는다.

검색 확장으로 정답 목록 밖의 후보도 2개 늘었다. `세 번 실패`에는 문구가 연속으로 있는 노을 자료에 이어 같은 단어들이 떨어져 있는 모래 API 자료가, `실패 알림`에는 참고 알림 자료가 추가됐다. 두 질문 모두 지정 정답은 1위였다. 회수율만으로 답변의 사실 정확도가 좋아졌다고 주장하지 않는다. 같은 주제의 다른 조건·주제 없는 키워드·정답이 없는 사실·오래된 결정을 포함한 실제 평가가 필요하다.

최종 실행의 p95는 CLI 검색 278.22ms, 지속 연결 MCP 검색 45.30ms, MCP 읽기 45.46ms였다. 대용량 쓰기/전체 테스트가 같은 호스트에서 실행 중인 작은 fixture의 단일 순회이며 성능 개선 또는 운영 SLO 근거로 사용하지 않는다.

## 검증 증거

- 구버전 제품에 새 어순/필터/MCP 검사 18개를 실행하여 **16 failed / 2 passed**를 재현했다. 로그 `/var/tmp/sb-query-before.log`. 미등록 단어가 포함된 두 음성 사례는 기존에도 통과했다.
- 최종 관련 회귀 **60 passed (10.49초)**. 봉인/비봉인, 짧은 단어/영숫자/연산자 문자, 정확한 문구 우선, 상태/종류/시간 필터, 분리 record 제외, record 선택 후 limit, schema 4/5 및 frozen 계약 호환을 포함한다. 로그 `/var/tmp/sb-query-focused-final2.log`.
- 표준 전체 회귀 **722 passed / 2 skipped (202.84초)**. `/var/tmp/sb-query-full-tests.log`. 기존 walking skeleton과 기억 수명주기/동시성/복구 검사를 포함한다. 위 집중 검사와 일부 중복되며 횟수를 합산하지 않는다. 이 전체 실행은 격리 worktree의 새 제품 코드에 대한 결과다.
- Ruff 전체 `sb tests` 통과. 변경 소스/테스트 basedpyright 오류 0이며 `sb/search.py`의 기존 경고 6개는 원 작업공간 기준 검사에서도 동일했다. 신규 query 모듈·변경 sealed/MCP/테스트의 타입 경고는 0이다. `/var/tmp/sb-query-ruff-final.log`, `sb-query-types-final.log`, `sb-query-types-baseline.log`.
- 최종 실제 CLI/MCP: `/var/tmp/sb-korean-search-e6j77lo9/evidence.json`, `cli.jsonl`, `mcp.jsonl`, `rankings.jsonl`. 로그 `/var/tmp/sb-korean-query-improved-final.log`. 100개 완료, exit 0, `state=measured`.
- 최종 평가의 제품 hash(`sb/` 기준 상대 경로): `49301dcd854ffdcb2a10a343dad4492fe6435da216ed36a2f7bc95da87109cbb`. 평가와 제품 hash가 실행 중 바뀌지 않았음을 도구에서 검사했다.
- 초기 개선 평가 `/var/tmp/sb-korean-search-qc9n0ig8`은 같은 회수 지표였다. 표와 지연 수치는 마지막 native 평가 한 건을 기준으로 한다.

## 보류와 계속할 범위

자연어/의역 30건은 여전히 미회수다. 임의 조사/질문어 제거, 일부 단어만 남기는 OR 확장, 근거 없는 동의어 치환으로 수치를 맞추지 않는다. 실제 질문과 근거를 확보하고 질의 분석·관련도·선택적 hybrid를 평가해야 한다. 현재 100개는 합성 개발 세트이므로 실제 사용자 질문 100–300개 인수를 대신하지 않는다.

짧은 단어는 기존 substring 의미를 유지하므로 영문 경로의 일부와도 일치할 수 있다. 전체 문구를 강제하는 별도 검색 모드, 혼합 Unicode casefold/형태소 처리와 다양한 질의의 비용은 후속 평가 항목이다. hybrid는 계속 꺼져 있으며 삭제/복원/세대/출처/범위 결합 전 활성화는 보류한다.

공통 기억의 프로젝트/사용자 접근 범위, 일반 agent의 삭제 후 fence, 자비스 정정 UI·원본 차단 전파, B5 context pack/전달 이력, 운영 전환/독립 복원과 100회 쓰기는 계속 남는다. 이번 검색어 어순 개선을 전체 목표 완료로 축소하지 않는다.
