# 허용 후보의 분류 중복 조회 제거

사전 scope 검사 후 기존 본문 reader가 같은 출처 분류를 다시 읽는 비용을 제거했다. private frozen `_PageClassification`에 현재 content_digest·요구 범위·source refs를 담아 해당 단일 read 호출에 전달한다. 전역 또는 요청 간 cache는 없다. Git 본문을 실제로 읽고 SHA-256이 사전 분류의 content_digest와 같은지 검사한 다음 record를 파싱한다. 최종 require_scope와 context 종료 시 전체 세대 검증은 유지한다. scope 없는 기존 reader는 원래 경로를 사용한다.

실제 봉인 fixture에서 일반 reader와 전체 ClassifiedPage 값이 동일하며, SQLite trace로 각 source classification SELECT가 출처당1회임을 확인했다. Git 반환 본문을 바꾸면 MEMORY_ACCESS_UNAVAILABLE로 거부한다. 관련 scoped/memory access/독립 writer 동시성/generation knowledge/search **49 passed / 13.21초**, Ruff sb/tests·타입0오류0경고·diff 통과. 이후 테스트의 nested with 스타일만 정리했으며 제품코드·assertion은 동일하다.

1,000페이지 각5회 순차 측정:

| 허용 페이지 | 질의 | p50 | p95(5표본 최대) |
|---|---|---:|---:|
| 1,000 | ScaleProbe | 2.3077초 | 2.3500초 |
| 1,000 | forbidden(원본 없음) | 0.2753초 | 0.2825초 |
| 1 | ScaleProbe | 0.4634초 | 0.4704초 |
| 1 | forbidden(불허 원본 존재) | 0.4590초 | 0.4688초 |

전체허용 p50은 직전2.4382초에서 감소했지만 최초2.1637초보다 높다. 서로 다른 실행의 소표본이므로 모든 차이를 코드 하나의 효과로 단정하지 않으며 회귀 비용 완전 해소로 처리하지 않는다. 여전히 후보마다 원장 연결과 조인 비용이 있고 더 큰 corpus/MCP/동시 갱신 측정도 남는다. 불허 다수의 개선과 본문 미노출은 유지했다. [원시 결과](SCOPED-CLASSIFICATION-ONCE-2026-09-10.json). 제품 변경 후 전체pytest·설치재빌드는 미실행이며 운영·M1–M14 전체 목표 유지.

후속 자비스 실제HTTP/CLI/MCP 전체 비모델 검증exit0. 독립stdio reader2개각2records, peer제한0/원agent2, 철회403/종료중만료401·변조/중복/재시작 검사통과. 결과 /var/tmp/page-access-acceptance-gwi2uqk9/scoped-mcp-result.json. 합성신원/clock·native0, 운영완료증거아님.
