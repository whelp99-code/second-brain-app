# 지식 상태 읽기 완료 시 세대 재검증

기존 설계 문서의 미구현 표시는 과거 시점이었다. 현재 원장 bound_knowledge, 세대 digest 결합, sealed lexical/vector 상태, effect 정정 및 복원 연결이 이미 존재하므로 재구현하지 않았다. 해당 설계 문서에 현재 구현과 후속 기록을 연결했다.

`sealed_knowledge_states`는 최초 manifest 검증 후 별도 SQLite 연결에서 상태를 읽고 즉시 반환했다. 최초 검증 직후 실제 원장의 승인 상태를 PENDING→APPROVED로 바꾼 결정적 회귀 검사에서 변경을 거부하지 못했다. 원래 승인된 본문에 대한 증거 없이 함수가 승인 상태를 반환하는 읽기 경계의 문제다. 전체 검색 외곽의 추가 검증을 모두 우회했다는 주장은 아니다.

변경: 결과를 조립한 뒤 기존 전체 세대 verifier를 다시 호출하고 최초 manifest와 동일함을 확인한 후에만 반환한다. 지속된 원장 변조·세대 불일치는 GenerationIndexError로 거부한다. 외부 registry 제한 우선순위·현재 본문 digest 결합·접근 권한은 변경하지 않았다. 공격자가 읽기 중 변조를 완전히 되돌리는 모든 경합이나 외부 정책의 전체 수명까지 해결했다는 증거는 아니다.

검증:

- 위 실제 SQLite 변경 회귀: 수정 전 DID NOT RAISE로 실패, 수정 후 거부.
- generation/bound/effect/restore knowledge와 search/hybrid filter/sealed vector 관련 **80 passed / 5.91초**.
- Ruff sb/tests 및 변경 모듈 basedpyright **0 errors / 0 warnings**, diff 통과.
- 실제 합성 봉인1,000페이지: 허용1개 검색2.2348초, 불허0개 검색2.1951초, peak RSS57,348KiB(생성 비용 포함). `/var/tmp/sb-scoped-scale-2dmzcq3g`, `/var/tmp/sb-knowledge-read-scale-20260910.json`. 단일 순차 실행이며 p95·MCP·동시 갱신 측정은 아니다.

이후 제품 수정이므로 앞선 전체1,730통과와 설치f0fec14 결과에 포함됐다고 표현하지 않는다. 운영 데이터·서비스 변경 없음. 실제 운영·사용자 업무·M1–M14 전체 완료 조건 유지.
