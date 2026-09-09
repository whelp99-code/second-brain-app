# 관리형 검색의 본문 결합 상태 연결

기준 소스 419747d. 컴파일→내부 상태 저장→세대 봉인→검색의 연결을 구현했다.

## 변경과 정책

`sb/sealed_knowledge.py`는 세대 manifest 검증 후 내부 원장의 bound_knowledge와 records를 page_id 및 content_digest 모두 일치하는 행으로 join한다. 이 투영을 SearchIndex의 sealed lexical과 semantic 경로에 함께 전달한다. 읽기는 read-only SQLite이며 missing external registry를 생성하지 않는다.

외부 registry의 ACTIVE/APPROVED 행만으로는 관리형 본문을 승격하지 않는다. canonical 값도 본문에 결합되지 않았으므로 해당 행에서 복사하지 않는다. 외부 상태가 ACTIVE/APPROVED가 아닌 명시적 철회·보류·후보·UNKNOWN이면 내부 자동 상태보다 우선한다. 후보 검색은 유지한다. 같은 ID의 오래된 내부 digest도 현재 본문에 일치하지 않으면 사용하지 않는다.

이는 관리형 검색의 의미 변경이다. 과거 외부 page-ID 승인만 있던 문서는 reference에서는 보이되 active에서는 제외된다. 자동 승격용 호환 예외를 넣지 않았다. 일반 비관리형 Git 검색의 외부 registry 동작은 이번 범위에서 변경하지 않았다. VERIFIED는 기존 자동 처리 상태의 본문 결합 표시이며 진실성·사용자 승인·접근권한 검증을 의미하지 않는다. 외부 철회의 저장소별 범위와 현재 요청 중 철회 경쟁은 별도 후속 과제다.

## 검증

`TMPDIR=/var/tmp uv run pytest -q tests/test_sealed_search.py tests/test_sealed_vectors.py tests/test_generation_vectors.py tests/test_mcp_sealed_vectors.py tests/test_generation_knowledge.py tests/test_generation_runtime.py --tb=short`: **69 passed / 12.54초**.

- 실제 임시 관리형 compile→본문 수정→후속 세대 publication 후 별도 Python 프로세스에서 active 검색 VERIFIED와 page ID 일치를 확인했다. 외부 registry 파일 생성 없음.
- 키워드/벡터 필터가 limit 전에 적용되고 후보·날짜·kind 동작을 유지한다. 벡터 외부 철회 후 active 결과 0건을 확인했다.
- 외부 ID-only 승인, 현재와 다른 내부 본문 digest는 승격되지 않는다. 세 가지 명시적 제한 상태가 내부 승인보다 우선한다.
- 기존 세대 변조 검증과 MCP 벡터 record 조회 테스트를 포함한다.
- Ruff 전체, diff, 변경 검색 모듈 타입 검사 0오류/0경고.

처음에는 기존 ID-only 승인 fixture가 새 정책과 충돌한 3건이 실패했다. 필터 테스트의 실제 본문에 상태를 봉인하도록 fixture를 바꾸고, ID-only 승인 거부를 별도 테스트로 추가했다. 이후 /tmp에서 SQLite disk I/O error로 44건 및 다음 실행 69건이 실패했다. 최소 1건으로 저장소 초기화 단계 오류를 확인하고 종료된 실행을 /var/tmp로 바꿔 통과했다. /tmp 원인 자체를 해결했다고 주장하지 않는다.

## 미완료·보류

전체 suite는 아직 이번 소스로 재실행하지 않았다. 실제 사용자 업무/native 모델 인수, 최신 설치본/자비스 쌍 검증, 정정·삭제·복원과 상태 수명, publication 실패/강제 종료, 대용량 조회 비용, 외부 철회 race와 범위, 일반 비관리형 stale 승인 문제 및 M1–M14는 남는다. 모든 상태를 읽는 추가 검증 비용은 실측 후 조정한다.

새 상태가 있는 세대의 구버전 reader 거부와 운영 보류는 유지한다. 이번 운영 저장소·서비스·공용 registry 변경이나 push는 없다.
