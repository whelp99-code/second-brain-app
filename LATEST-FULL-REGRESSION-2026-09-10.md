# 최신 누적 변경 전체 회귀

검사 전후 HEAD: `f9fbe55c6a2a07d768e20577b99d2a47fbd2ab24`.

실행: `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`

결과: **1,730 passed / 2 skipped**, **516.23초**, 종료 코드0. [원본 출력](LATEST-FULL-REGRESSION-2026-09-10.txt). 이전 전체1,724통과 이후의 완료 실패 보고·동일 이름 원본 보존·검증 직후 입력 교체 차단 회귀를 포함한다. 지정한 optional embeddings 모듈 전체는 실행 범위에서 제외했다.

검사 중 제품 코드·테스트는 변경하지 않았다. 종료 후 HEAD 동일과 변경 파일이 IMPLEMENTATION-STATUS.md뿐임을 확인했다. 검사 중 수행한 변경은 상태 문서 첫머리의 최신 근거 표 추가이며 이후 결과를 반영했다. Ruff sb/tests 및 diff 검사 통과.

설치물 연동은 별도 [최신 설치 인수](INSTALLED-INBOX-PAIR-2026-09-10.md), 실제 Claude/Codex 결과는 [클라이언트 인수](SCOPED-ACCEPTANCE-CLOCK-2026-09-10.md), 운영 전환 보류는 [운영 관측](MAINTENANCE-CLI-AND-OPS-2026-09-10.md)를 따른다. pytest 성공은 실제 운영 배포, 사용자 업무 계보, 모든 에이전트의 수집·주입·삭제 수명 완료를 의미하지 않는다. M1–M14 전체 목표는 유지한다.
