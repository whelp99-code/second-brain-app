# Scoped 후보의 불필요한 표시용 본문 읽기 제거

`SearchIndex.iter_lexical_hits`는 status/updated/source_ref 표시값을 얻으려고 committed 본문을 읽고, scoped 소비자는 동일 페이지를 다시 읽어 본문 digest와 모든 출처의 접근 분류를 검사했다. scoped 결과는 그 표시값을 사용하지 않았다.

후보 iterator에 기본 true인 `include_metadata`를 추가했다. scoped 내부 호출만 false로 지정한다. knowledge 상태/승인/종류 필터는 항상 유지하고, 명시적 status/날짜 필터가 있으면 false여도 본문 메타데이터를 읽어 검사한다. 일반 검색의 기본 응답과 공개 MCP 계약은 변경하지 않았다. 본문·출처·owner/project/revision 검사는 기존 classified reader에서 유지하며, 응답 반환 전 세대 검증과 pin 수명도 유지한다.

새 회귀 검사는 metadata 생략 전후 reference/active/candidate 범위, 상태, 날짜 상·하한, 종류 필터의 후보와 knowledge/approval 상태 일치를 확인한다. 최종 코드 관련 봉인 검색/scoped 검색/접근 검사/MCP scoped/독립 writer 동시 갱신 **60 passed / 21.97초**. Ruff 전체·변경 모듈 타입0오류0경고·diff 통과. 전체 테스트를 다시 실행한 수치는 아니다.

동일 스크립트 합성1,000페이지 생성·봉인·검색 순차 단일 실행, exit0:

| 질의 | 이전 초 | 수정 후 초 | 결과 |
|---|---:|---:|---|
| ScaleProbe | 4.3283 | 2.1688 | 허용1 |
| forbidden | 4.3941 | 2.1647 | 0 |

약50% 감소. peak RSS57,960→58,312KiB(세대 생성 포함). [원시 결과](SCOPED-CANDIDATE-PROJECTION-2026-09-10.json). p95/운영 지연 보장으로 확대하지 않는다. 최초1,000페이지5.25초 측정 이후 YAML 중복과 표시용 본문 중복 읽기를 순서대로 줄였다.

성능 개선의 다음 인수 단계는 최신 설치 후보에 이 변경을 포함해 자비스 paired 연결을 재검증하는 것이다. 최신 운영물에는 아직 미적용이다. 실제 사용자 업무·native 수명·운영 전환과 전체 M1–M14는 계속 남는다.
