# 복원·충돌 변경 통합 회귀

검증 대상: 0445d7ea5d26b175e873c365d2f8305d0adfb0eb. 복원 지식 상태/접근 요구사항, 원장 저장 실패 후 재시도, 별도 MCP 프로세스 조회, fake 충돌 응답, JSON parser와 입력 인용 제한·cache 갱신을 포함한 제품/테스트 소스다. 실행 중 제품·테스트 소스 변경 없음.

명령: `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`. 선택 embeddings extra 테스트는 명시적으로 제외하며 기본 suite를 검증한다. 원본 실행 로그는 /var/tmp/sb-conflict-restore-full-20260910.log다. **최종 결과: 1,690 passed, 2 skipped / 438.89초, exit0.** [보존 로그](CONFLICT-RESTORE-FULL-2026-09-10.txt).

Ruff 전체 통과. conflict/restore/restore_access/restore_knowledge 타입0오류0경고. 이 타입 검사 범위 밖 모듈까지 경고가 없다고 주장하지 않는다.

전체 suite는 코드 회귀 증거다. 실제 JARVIS DB 발급 권한으로 삭제 이력이 증가한 복원 세대를 읽는 인수, 운영 journal 소실 DR, 실제 사용자 업무 및 모든 에이전트 수집·주입·삭제 수명/운영 배포의 완료 증거는 아니다. 운영 변경과 push 없음. 전체 M1–M14 목표를 유지한다.
