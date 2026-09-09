# 운영 lease 만료 구분

기준fabd688. JARVIS gjc-configuration-store.ts 및 microloops.ts의 lease 획득/갱신 코드는 UTC milliseconds ISO 문자열을 기록하고 expires_at > now를 유효 경계로 사용한다. pending-state 관측 도구에도 같은 만료 경계를 적용했다. 관측 시각은 timezone-aware로 고정해 출력하며 두 lease 테이블의 unexpired/expired/invalid 건수만 보고한다. 소유자·원문은 출력하지 않는다.

잘못된 날짜, 비정규 시각, NULL/숫자는 만료로 간주하지 않고 invalid에 집계한다. expires_at == now는 expired다. lease가 유효하다는 것은 그 시각의 만료 조건에 관한 관측이며 실제 프로세스 생존·진행 중 작업을 독립적으로 증명하지 않는다. drain_authorized=false 유지.

관련4통과/0.24초·Ruff/diff 통과. 실제 읽기 전용 운영 관측 2026-09-09T19:08:38.481034+00:00 (한국9월10일04:08)에서 GJC unexpired1/expired0/invalid0, microloop 전부0, 큐6개는0행, active cursor0. 실행exit0, 원시 지역 결과 /var/tmp/sb-lease-observation-20260910.json.

따라서 남은 lease를 오래된 빈 행으로 간주해 제거하지 않는다. 기존 DB 사용 서비스2개/관측권한 부족과 함께 운영 전환 보류 근거로 유지한다. 큐 비움은 실행권 해제와 다르다. DB/서비스·타 리포 변경이나 push 없음. 제품 provider 코드 미변경, 관측 도구 개선이며 실제 업무·운영 및 전체 M1–M14 미완료.
