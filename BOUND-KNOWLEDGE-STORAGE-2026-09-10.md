# 본문에 결합된 지식 상태: 저장 기반 구현

기준 소스 327183d 위의 변경. 자비스 인계서의 세컨드브레인 정본·여러 에이전트 공통 기억 방향을 유지한다. 네 OSS를 설치하거나 별도 기억 DB를 추가하지 않았다.

## 구현과 근거

- `sb/bound_knowledge.py`: canonical wiki/daily/conflicts 페이지 ID와 sha256 본문 digest에 상태를 결합하는 불변 타입. 경로 이탈·proposal·비정규 ID·잘못된 digest 및 상태를 거부한다. 상태는 접근 권한이나 사실의 진실성을 보증하지 않는다.
- `sb/store/ledger.py`: 원장 schema 5의 additive `bound_knowledge` 테이블. 기본키는 `(page_id, content_digest)`. 동일 상태 저장은 멱등이며 같은 키의 다른 상태는 충돌로 거부한다. 철회 정책의 최종 API가 아니라 컴파일 시점 기록용 기반이다.
- 페이지 ID만 같고 본문 digest가 다르면 상태 조회 결과는 없다. 외부 registry의 오래된 승인 행을 옮기거나 일괄 승격하지 않는다.
- 기존 SQLite transaction과 원장 마이그레이션을 재사용한다. v4 형식 fixture의 기존 run 보존, v4 백업 보존, v5 재마이그레이션 멱등, 재접속 후 상태 유지, 외부 transaction rollback을 검증했다.

## 검증

`uv run pytest -q tests/test_bound_knowledge.py tests/test_store_ledger.py tests/test_ops.py tests/test_generation_access.py tests/integration/test_walking_skeleton.py`: **71 passed / 3.76초**.

`uv run ruff check sb tests`와 `git diff --check` 통과. 초기 Ruff 정렬·중첩 with 지적 두 건을 수정했다. 테스트는 임시 저장소 대상이며 이번에 운영 원장·서비스·공용 registry를 변경하지 않았다. 과거 공용 registry 테스트 영향은 별도 REGISTRY-TEST-IMPACT 보고서가 유효하다.

## 이어갈 구현 및 완료 조건

1. 실제로 적용된 컴파일 본문만 상태로 기록하고 실패·proposal은 제외한다.
2. 정규화된 상태 행을 세대 원장 digest에 명시적으로 포함한다. 현재 추가 테이블은 기존 digest의 검증 대상이 아니다. 상태가 없는 기존 세대 호환성도 유지한다.
3. 같은 세대·본문 상태를 lexical/vector 검색에 연결한다. 외부 철회·비활성 우선순위를 검증하고 페이지 ID만 맞는 오래된 승인을 배제한다.
4. 본문 교체·삭제·복원·publication 실패·강제 종료·다른 프로세스 조회를 인수한다.

현재 pipeline과 검색은 새 API를 호출하지 않는다. 따라서 이 커밋은 관리형 VERIFIED 문제 해결 완료나 운영 배포 완료가 아니다. 전체 테스트의 최신 기존 기준선과 이번 집중 검증을 구분한다. 최신 설치본 갱신, 실제 사용자 업무의 다른 에이전트 회수, 클라이언트별 자동 수집·주입, 검색 품질, 삭제·복구와 운영 인수 및 M1–M14는 계속 남는다.
