# 복원 작업공간 수정 전체 회귀

검사 제품 커밋: f45a1a1f043ad45d205785ce31ab52ba7222024f. 검사 전후 HEAD 동일, 제품/테스트 변경 없음. 기존 미추적 사용자 파일 네 항목 유지.

`TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`

결과: **1698 passed, 2 skipped in 437.74s (0:07:17)**, 프로세스 exit0. [전체 출력](RESTORE-WORKSPACE-FULL-2026-09-10.txt). 선택 embeddings extra 테스트는 제외했다. Ruff sb/tests 통과, basedpyright sb/restore.py sb/restore_workspace.py 0오류/0경고. 이전 부분 회귀 결과를 최신 전체 결과로 대체한다.

실제 JARVIS 런타임 백업·동시 scoped client·재삭제/재복원 인수는 [별도 결과](RESTORE-WORKSPACE-RECOVERY-2026-09-10.md)를 따른다. 이 전체 자동 회귀가 운영 인증·설치 버전·실제 사용자 업무·다른 모델 간 자동 수집/주입을 증명하지 않는다.

다음 구현 경계도 읽기 전용으로 대조했다. sb maintain → GenerationMutationService._maintain_locked는 generation staging과 export를 정리하지만 sanitizer에 넘기는 임의 workspace는 등록되어 있지 않다. 관리 대상 경로를 명시해야 유지관리에서 중단 해제 사본을 정리할 수 있다. 복원은 workspace 잠금 후 generation 잠금을 얻으므로, 세대 잠금을 가진 maintenance는 workspace 잠금을 기다리지 않고 busy를 건너뛰어야 교착을 피한다. 구형 잠금 미참여 writer와 혼합 운영, 구형 이름 복구 사본의 자동 삭제는 계속 보류한다. 이번에는 설계 대조만 했고 이 유지관리 연결을 구현하지 않았다.

운영 서비스·DB·타 리포 변경이나 push 없음. 전체 M1–M14 목표는 미완료 상태다.
