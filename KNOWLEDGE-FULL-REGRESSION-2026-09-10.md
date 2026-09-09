# 지식 상태 연결 후 전체 회귀

제품 기준 5d2e820d69d026f01c6348bef2919c8c92d534ca.

`TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`: **1 failed, 1605 passed, 2 skipped / 313.89초**. 원문 로그는 KNOWLEDGE-FULL-REGRESSION-2026-09-10.txt.

유일한 실패는 test_source_access의 legacy migration 테스트가 최신 schema를 숫자 4로 고정한 부분이다. 실제 version 5가 반환됐으며 기존 source 보존 및 접근 분류 없음은 이미 통과했다. 제품 코드를 변경하지 않고 CURRENT_SCHEMA_VERSION과 비교하게 수정했다. 추가로 bound_knowledge도 0행임을 검증해 기존 데이터를 자동 승격하지 않는 조건을 확인한다.

수정 후 `TMPDIR=/var/tmp uv run pytest -q tests/test_source_access.py tests/test_bound_knowledge.py tests/test_generation_knowledge.py`: **33 passed / 2.82초**. Ruff 전체와 diff 검사 통과. 테스트 수정 후 전체 suite를 다시 실행한 결과는 아니므로 전체 green 실행이라고 표기하지 않는다.

병행 읽기 감사는 KNOWLEDGE-LIFECYCLE-AUDIT-2026-09-10.md. 정정·부분 삭제의 살아남은 본문과 복원 문서에 새 지식 상태를 기록하는 연결이 없으며 이는 다음 구현/인수 대상이다. 기존 상태를 무조건 복사하는 우회는 보류한다. 실제 native 사용자 업무, 최신 설치 쌍, 운영·복구와 M1–M14 전체 목표는 여전히 미완료다.

이번 운영 DB·서비스·공용 registry 변경 없음. 제품 소스는 변경하지 않았다. 사용자 기존 파일은 유지했으며 push 없음.
