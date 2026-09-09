# 복원 SIGKILL: 재시도 통과와 삭제 원문 잔류 발견

기준 8c14978 이후 검사. 새 `tests.restore_kill_worker`가 독립 Python 프로세스에서 실제 sanitizer를 호출한다. 원본 해제 직후와 후보 본문 materialize 직후 각각 자신에게 SIGKILL을 보내고, 부모는 returncode=-9를 검사한다. 같은 요청을 또 다른 새 프로세스로 재시도한다. sleep이나 예외를 SIGKILL로 대신하지 않았다.

`TMPDIR=/var/tmp uv run pytest -q tests/integration/test_restore_process_kill.py --basetemp=/var/tmp/sb-restore-kill-audit-20260910` 결과 2 passed/6.36초. 활성 세대와 그 ledger 해시, 삭제 high water가 그대로이고 재시도 후보에 삭제 원문이 없으며 proof blocked/scan=0, generation staging이 비었음을 확인했다. Ruff sb/tests 및 diff 검사 통과. 키·시각·내용은 fixture다. 실제 업무/전원 손실/운영 배포 인수가 아니다.

## 새 P0: 해제 작업공간의 삭제 전 원문 잔류

성공한 재시도 후 별도 파일 검사를 실행했다. 두 시나리오 각각 `restore/` 아래 24개 파일이 남았고 3개 파일에 삭제한 `ExampleAlpha 예시기록` 바이트가 있었다. 재현 위치는 위 basetemp의 test_restore_sigkill_preserves0/restore 및 test_restore_sigkill_preserves1/restore다. 모두 합성 시험 자료다.

원인: sanitizer가 mkdtemp로 매번 새 작업공간을 만들고 현재 호출의 finally/except 경로에서만 정리한다. SIGKILL은 정리를 실행하지 않으며 다음 호출은 이전 디렉터리를 회수하지 않는다. 후보 검색에서 재노출되지는 않았지만 삭제 수명 전체 완료를 막는다. 이번 통과 테스트는 활성 상태와 재시도의 증거일 뿐 잔류 삭제 성공을 주장하지 않는다.

복원 운영 완료 판정은 보류한다. 다음 수정은 작업공간 사용 중 여부를 잠금으로 판별하고, 다른 살아 있는 복원 작업을 지우지 않으면서 중단된 해제 사본을 회수하는 것이다. 경로 이름이나 나이만으로 디렉터리를 일괄 삭제하는 우회는 적용하지 않는다. 강제 종료 후 재시도·다른 동시 복원·심볼릭 링크 경계를 검증해야 한다. 현재 제품 코드는 아직 수정하지 않았으며 원문 잔류 결함은 미해결이다.
