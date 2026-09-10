# scoped 조회 내 읽기 연결 공유

사전 분류 조회가 후보마다 SQLite 연결을 열던 비용을 제거했다. generation을 최초 검증한 뒤 해당 scoped context에 mode=ro&immutable=1 연결 하나를 열고 후보들이 공유한다. context 종료 시 reader를 비활성화하고 연결을 닫은 다음 전체 generation을 다시 검증한다. 오류 종료도 finally에서 연결을 닫는다. scope 없는 기존 reader 경로는 변경하지 않았다. 요청 간 cache/연결 풀/공유 mutable 상태를 만들지 않았다.

실제 SQLite 연결 관측 테스트에서 같은 페이지2회 읽기에 분류 연결1개, 정상 종료와 호출자 RuntimeError 종료 모두 실제 연결의 SELECT가 closed 오류로 거절되고 reader 재사용도 거절되는 것을 확인했다. 기존 본문 hash 변조·전체 분류·종료 전 generation 변조·독립 writer 동시성 검사는 유지했다. 관련 **51 passed / 16.16초**, Ruff sb/tests·변경모듈 basedpyright **0 errors / 0 warnings**, diff 통과.

1,000페이지 각질의5회 순차 실행:

| 허용 페이지 | 질의 | p50 | p95(5표본 최대) |
|---|---|---:|---:|
| 1,000 | ScaleProbe | 2.0231초 | 2.0262초 |
| 1,000 | forbidden(원본없음) | 0.2799초 | 0.2895초 |
| 1 | ScaleProbe | 0.3167초 | 0.3190초 |
| 1 | forbidden(불허원본존재) | 0.3102초 | 0.3192초 |

직전 전체허용 p50 2.3077초·허용1개 0.4634초보다 낮았고, 최초 전체허용 기준2.1637초보다도 낮았다. 이번 소표본에서 앞서 관측한 추가 비용은 재현되지 않았다. 서로 다른 시점의 합성 library 측정이므로 운영 SLA·MCP 왕복 지연·모든 corpus에 대한 우위를 입증하지 않는다. 매회 결과 assertions 통과/exit0, [원시 결과](SCOPED-SHARED-READ-2026-09-10.json). 운영·전체 요구사항 M1–M14 유지.

후속 실제 자비스HTTP/CLI/MCP 전체 비모델 시험exit0: 독립stdio2개각2records, 다른agent제한0/원agent2, 철회403/만료401, 응답변조/중복/재시작 검사통과. /var/tmp/page-access-acceptance-l_05d7_i/scoped-mcp-result.json. 합성신원/clock·native0, 운영배포·전체회귀·설치물검증과구분한다.
