# 불허 검색 후보의 본문 읽기 생략

기존 scoped 검색은 후보마다 Git cat-file로 본문을 읽고 record를 파싱한 뒤 require_scope로 제외했다. 전체1,000페이지 중 허용1개인 corpus에서는 불허999개에도 이 비용을 지불했다.

기존 generation 검증 context 안에서 선택적 scope 사전 검사를 추가했다. 봉인 원장의 records와 page_access를 페이지 ID와 정확한 content_digest로 조인하고, 완전한 출처 분류를 읽어 기존과 같은 owner/project/policy_revision 조건으로 거부한다. 분류 없거나 불완전하면 unclassified다. 통과한 후보는 기존 Git 본문 hash/분류 검증·record 파싱과 require_scope를 다시 수행한다. 사전 검사를 통과했다는 이유로 권한을 부여하지 않으며, 조회 전후 세대 검증·허용 결과 이후 limit·최종 결과 버퍼링을 유지한다. 범위 조건을 한 helper로 공유해 두 검사 규칙의 차이를 방지했다.

검증:

- 실제 세 원본(불허·미분류·허용) 컴파일 회귀에서 결과1개는 유지하면서 직접 Git blob 읽기1회. 불허 질의와 다른 owner 질의는 결과0개 및 직접 blob 읽기0회.
- scoped search/memory access/독립 writer 동시성/generation knowledge/search **47 passed / 18.05초**.
- Ruff sb/tests·변경 모듈 basedpyright **0 errors / 0 warnings**·diff 통과.
- 동일 합성1,000페이지(허용1개), 각 질의20회: 허용 p50 **0.4616초**, p95 **0.4719초**; 불허 p50 **0.4531초**, p95 **0.4662초**. 모든40회 허용1/불허0. 기존 기준선 p95는 각각2.2905/2.1982초. [원시 결과](SCOPED-EARLY-DENIAL-2026-09-10.json), `/var/tmp/sb-scoped-scale-adc81516`.

이 비교는 다른 실행 시점의 합성 provider library 소표본이다. 새 benchmark의 실행 초반에는 관련 pytest 실행이 겹쳤으며 독점 CPU 조건을 주장하지 않는다. 두 실행 모두 단일세대/순차 질의이며 MCP·모델·운영 p95는 아니다. 대부분 허용된 corpus에서는 추가 원장 조회 비용이 생기므로 모든 데이터에서 같은 개선을 주장하지 않는다. 별도 전역 cache·정책 예외·그래프를 도입하지 않았다.

후속 실제 연결 인수: `scoped-mcp-acceptance.py`와 기존 격리 자비스 빌드의 전체 비모델 시험 exit0. HTTP→CLI→MCP의 독립 reader2개 각record2개, 다른 agent의 제한0개/원래agent2개, 정책철회403·종료중만료401, 응답변조·중복제출·재시작 검사 통과. 결과 `/var/tmp/page-access-acceptance-e6iy56o3/scoped-mcp-result.json`, 로그 `/var/tmp/sb-prefilter-mcp-20260910.log`. 합성 신원/시각이며 이번 native 호출0회. 운영배포·전체회귀·설치재빌드와 M1–M14 전체 인수는 별도다.
