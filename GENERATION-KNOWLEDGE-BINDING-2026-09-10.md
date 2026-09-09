# 지식 상태를 세대 검증 해시에 결합

기준 소스 047bb67. 이전 저장 기반에 이어 `sb/generation_access.py`의 공통 writer/reader digest 계산에 상태 행을 결합했다.

## 변경

- 동일 SQLite 읽기 transaction에서 `bound_knowledge`를 page_id/content_digest 순서로 읽고 각 행의 타입·값 및 중복 키를 검증한다.
- 기존 access digest 위에 `knowledge-bound-ledger-v1` profile로 정규화된 상태 목록을 결합한다. build와 read verifier가 동일 함수를 사용한다.
- 상태가 없거나 테이블이 없는 세대는 기존 digest 그대로 유지한다. 기존 source/page 접근 분류 결합은 유지한다.
- 승인·지식 상태, 페이지 ID, 본문 해시 변경 및 행/테이블 삭제는 세대 검증 실패로 이어진다. 공격 fixture에서 derived 파일 inventory를 다시 계산해도 실패한다.

## 검증

`uv run pytest -q tests/test_generation_knowledge.py tests/test_generation_access.py tests/test_bound_knowledge.py tests/test_sealed_search.py tests/integration/test_walking_skeleton.py`: **68 passed / 4.85초**.

실제 임시 세대를 생성·봉인하고 별도 Python 프로세스에서 검증기를 실행해 같은 generation_id를 회수했다. 이는 격리된 합성 데이터의 실제 저장/검증 경로이며 사용자 업무 또는 native 모델 인수 결과는 아니다.

새 generation_access 타입 검사 0 오류/0 경고, Ruff 전체 및 diff 검사 통과. 이전 bound_knowledge 타입의 의도적 런타임 isinstance 검사는 정적 분석에서 4개의 unnecessary-isinstance 경고가 남는다. 최초 검사에서 추가된 Any/문자열 결합 경고는 수정했다.

## 미완료와 호환 경계

- 컴파일에서 실제 적용 본문 상태를 기록하는 연결과 lexical/vector 조회 연결은 남는다. 이 변경만으로 검색 VERIFIED 표시가 달라지지 않는다.
- 모든 저장 상태 행을 봉인하지만 해당 digest가 현재 페이지와 같은지 판단하는 검색 정책을 아직 구현하지 않았다. 과거 본문 상태가 남을 수 있으며 이를 현재 본문에 승계해서는 안 된다.
- 외부 registry 철회·비활성, 정정·삭제·복원·실패 publication 인수는 후속 범위다.
- 신규 상태가 있는 세대는 이전 reader가 digest 불일치로 거부한다. 새 상태가 없는 기존 세대의 호환성과 구분한다. 운영 활성화·구버전 rollback 가능성을 주장하지 않는다.
- 운영 서비스/DB/공용 registry 변경과 push 없음. 최신 설치본 갱신, 실제 에이전트 업무 공유와 M1–M14 완료는 아직 증명되지 않았다.
