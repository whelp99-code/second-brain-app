# 범위 쓰기의 활성화 직후 중단·만료·철회 복구 수정

2026-09-09. 이전 인계 재대조에서 재현한 A1의 수정이다. 전체 M1~M14 목표 중 내부 v4 복구 경로를 보강하며, 공개 쓰기 계약과 실제 운영 권한 연결까지 완료한 것은 아니다.

## 문제와 수정

활성 세대 포인터 저장과 요청 원장의 activated 전환 사이에 프로세스가 종료될 수 있다. 원장은 switch_intent인데 데이터는 이미 활성이다. 기존 실행기는 만료되거나 권한이 철회된 재개를 새 쓰기처럼 거부하여, 완료 proof 없이 reconciling을 반복했다.

`sb/request_executor.py`는 먼저 기존 봉투·원장 identity·수락 시각·file digest 검증을 그대로 수행한다. 그 뒤 switch_intent/activated/disposing/proved 단계이고, 요청에 기록된 result_generation_id가 현재 활성 세대와 정확히 같을 때에만 이미 적용된 결과의 복구로 분류한다. 활성 세대 읽기는 기존 manifest·git head/tree 검사 경로를 사용한다.

세대 전환 hook에서 같은 조건을 다시 검사한다. 이 지점은 기존 generation mutation service의 writer lock 안이다. 원장 phase만 믿는 만료 예외는 제거했다. 새 materialization은 단계와 무관하게 만료·현재 권한 검사를 수행한다. 따라서 최초 검사 이후 활성 세대가 바뀌어도 새 쓰기 권한을 얻지 못한다. 기존 generation mutation의 base·tombstone 검사, reingress 차단, proof·영수증 기록을 재사용한다.

복구 완료 영수증은 이미 적용된 결과의 역사적 처리 증거다. 철회된 사용자에게 기억 본문을 다시 읽을 권한을 부여하지 않는다. 읽기 정책과 실제 자비스의 현재 권한 검증은 별도이며 그대로 필요하다.

## 검증

- 신규 실제 자식 프로세스 종료 테스트: sealed_manifest / pointer_parent_fsync 두 지점과 만료 / 철회 두 조건을 조합했다. lease는 1초, 철회 재개는 명시 시각 +2초로 설정해 만료와 구분한다. sleeps는 사용하지 않는다.
- 초기 테스트 작성에서 철회 시각을 +2분으로 두어 fixture 만료까지 겹쳤다. 시각과 lease를 수정한 뒤 제품 수정 전에는 활성화 후 재개 두 경우가 실패하고 활성화 전 거부 두 경우는 통과했다.
- 제품 수정 후 execution/admission/v3/walking skeleton **46 passed / 11.65초**. 새 기억 materialization이 호출되면 테스트가 실패하도록 했으며, 성공 복구는 같은 세대·같은 request/scope proof·추가 세대 없음·다음 실행 idle을 검증한다. 전체 Ruff와 diff 검사도 통과했다. 변경 실행기 basedpyright는 0 errors / 0 warnings / 0 notes였다.
- 별도 실행: 이전 수정 전 감사에서 두 번 reconciling이었던 임시 provider를 그대로 재사용했다. 새 프로세스에서 만료와 callback 철회를 동시에 적용해도 기존 결과를 proved로 완료했다. 새 세대 0개, 영수증 proved, 같은 scope proof, 재실행 idle이었다.
- 이후 독립 reader 프로세스는 허용 프로젝트에서 4 records, 다른 프로젝트에서는 MEMORY_ACCESS_DENIED를 반환했다. [재현 결과 JSON](SCOPED-RESUME-FIX-2026-09-09.json).
- 기존 `scripts/scoped-request-execution-acceptance.py`의 정상 경로도 새로 실행해 7개 독립 프로세스의 수락·실행·reader 3개·재수락·idle 검증을 통과했다.

최종 전체 Python 회귀 검사는 **1,212 passed / 2 skipped / 221.83초**다. optional `tests/test_embeddings.py`는 기존 gate대로 제외했으며 JARVIS 전체 검사는 포함하지 않는다.

## 남은 범위와 보류

여기서 권한 callback과 데이터는 시험용이다. 실제 authenticated transport·현재 정책·자비스 승인 소비 증거를 확인하는 검증기, v4 공개 MCP/패키지 계약, 자비스 outbox·영수증 소비는 아직 연결해야 한다. 운영 CLI에 True callback을 연결하거나 구형 원장/계약 검사를 풀어 활성화하는 방식은 보류한다.

이번에는 해당 요청의 결과가 현재 활성 세대인 복구를 검증했다. 이후 다른 세대가 활성화된 복구, 동시 정책·삭제 이력 변경, 원본 정정·삭제·복원과 native session 수명, 실제 에이전트/운영 인수까지 일반화하지 않는다. 전체 목표는 계속 진행한다. 운영 데이터·설정·서비스는 변경하지 않았다.
