# 같은 어댑터의 여러 원본 수집 결함 수정

2026-09-09 제품 `db685e9`. 이전 검색 인수에서 markdown-vault 세 source를 설정해도 첫 source만 원장에 들어가는 결함을 확인했다. 이번 단계는 해당 배치 수집 경로를 수정했다.

## 변경

기존 registry의 adapter 종류별 발견은 유지한다. pipeline이 설정 row별 격리된 Config로 발견한 인스턴스 중 해당 source ID의 인스턴스를 선택해 기존 종류별 인스턴스를 대체·확장한다. 따라서 같은 어댑터의 다른 ID/root를 서로 덮어쓰지 않는다. 단일 source ID 선택과 adapter ID 선택을 모두 유지한다.

같은 ID가 여러 설정에 중복되면 `SOURCE_ID_DUPLICATE`, 하나의 설정 ID가 여러 어댑터와 충돌하면 `SOURCE_ID_AMBIGUOUS`로 거부한다. 인스턴스 선택에 staging vault 설정을 사용하여 관리형 세대의 문맥을 유지한다. connector registry 파일을 수정하지 않았고 새 connector도 추가하지 않았다.

## 검증

- 기존 scoped search의 우회 수집(원본별 별도 ingest)을 제거했다. 한 번의 ingest에서 허용/불허/미분류 세 원본을 수집한 후 동일한 권한 검색 검사를 통과했다.
- 관련 집중 검사 **23 passed, 5.46초**: scoped search, ingest budget, generation runtime, source classification.
- Ruff·diff 통과. pipeline basedpyright 0 오류, 기존 미사용 KnowledgeState 반환 경고1.
- 실제 CLI `/var/tmp/multi-source-ingest-l9gdn69_/result.json`: adapter ID로 최초 source3/classification3/cursor3 수집; 재실행 snapshot 동일; B만 수정 후 source version4/classification4, A/C cursor 동일·B cursor 변경; 중복 ID 거부 및 데이터 snapshot 보존.
- 전체 회귀 **1,138 passed, 2 skipped, 201.63초** (`pytest -q --ignore=tests/test_embeddings.py`). 선택 embeddings extra 검사는 제외했고 집중 검사와 합산하지 않는다.

## 범위와 잔여 목표

이번 실제 검증은 markdown-vault의 여러 root다. 개별 factory가 source ID를 지원하지 않는 다른 connector의 임의 ID 확장이나 모든 adapter 조합을 검증한 것으로 확대하지 않는다. 파일이 없는 root의 기존 처리와 readonly DB connector 경계는 유지한다. 향후 factory별 지원표와 명시적으로 선택했지만 일치하지 않는 source 진단을 보강할 여지가 있다.

이 결함 때문에 보류했던 markdown 다중 원본 배치 수집 판정은 위 인수 범위에서 해소했다. 자비스 운영 권한 resolver, 나머지 scoped 표면, 원작업 계보·native 세션 사본·실제 앱·여러 writer·검색 성능/품질·GUI/DR 등 전체 목표는 유지한다. 격리 임시 파일/원장만 사용했으며 운영 서비스 재시작·vault/config 변경·push는 하지 않았다.
