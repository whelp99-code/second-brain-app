# 검색 메타데이터 단일 해석

직전 profile에서 1,000페이지 후보의 frontmatter 해석3,000회를 확인했다. `sb/page_metadata.py`의 기존 scalar YAML 해석을 `frontmatter_values`로 재사용하고, `sb/search.py`의 봉인 검색 및 증분 색인에서 status/updated/source_ref를 한 번 해석한 결과에서 읽도록 수정했다. 단일 필드 API는 유지한다. 전역 cache나 접근 제한 생략, 파서 정책 변경은 없다.

검증: 검색·증분 색인·봉인 검색·scoped 검색·독립 프로세스 동시 갱신 **59 passed / 8.02초**. 기존 날짜/상태 필터와 인용된 YAML 값 검사를 포함한다. Ruff 전체/diff 통과. 변경 모듈 basedpyright는0오류, 기존 `loader.dispose()` 호출의 partially unknown 경고1개를 보고했다. 전체 회귀를 재실행한 결과로 확대하지 않는다.

실제 합성1,000페이지 생성/봉인/검색 스크립트 실행exit0:

| 질의 | 이전 초 | 수정 후 초 | 반환 |
|---|---:|---:|---|
| ScaleProbe | 5.2513 | 4.3283 | 허용1 |
| forbidden | 5.2034 | 4.3941 | 0 |

단일 순차 실행 비교에서 약16–18% 감소했다. peak RSS58,088→57,960KiB는 세대 생성 포함이다. [원시 결과](SEARCH-METADATA-ONCE-2026-09-10.json). 반복분포/운영/MCP/native 성능은 미측정이며 별도 profile 비용을 위 수치에 섞지 않았다.

페이지별 Git 읽기의 반복 비용은 여전히 남는다. 다음에는 committed blob 읽기를 공유하면서 content digest·출처 결합을 유지하는 방법을 검토한다. 운영 배포와 실제 사용자 업무 인수 및 M1–M14 전체 목표는 계속 남는다. 이번에는 외부 의존성·공개 MCP 계약·자비스 소스를 변경하지 않았다.
