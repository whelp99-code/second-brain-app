# 미완료 배치의 다음 실행 시 중단 판정

일반 vault에서 작성 프로세스가 종료되면 batch의 running 기록이 남는다. 다음 전체 배치가 같은 단일 작성자 잠금을 얻은 뒤, finished_at이 없는 이전 running batch만 interrupted로 전환한다. 해당 시각은 실제 종료 순간을 추정한 값이 아니라 다음 배치가 중단을 확인한 시각이다. 과거 실행 ID와 다른 종료 상태는 보존한다. 성공으로 자동 변경하거나 처리 내용을 재실행하지 않는다.

Ledger.interrupt_stale_batches는 잠금을 보유한 pipeline에서만 호출한다. 살아 있는 작성자가 잠금을 보유하면 새 호출은 already_running으로 반환하며 원장을 변경하지 않는다. 예외 처리와 별개로 실제 SIGKILL 뒤에도 다음 배치에서 상태가 정리되는지 검증했다.

최종 crash/run_all/store ledger/runtime reliability/ops **57 passed / 9.16초**, Ruff/diff 통과. 별도 스크립트에서도 임시 저장소의 실제 자식 작성자를 단계 barrier에서 종료하고 원장을 새로 읽었다. 이전 running→interrupted, 새 배치ok 및 생존 작성자 보존을 확인했다. [원장 결과](BATCH-CRASH-RECOVERY-2026-09-10.json). stage는 대기용 합성 함수이며 모델 호출은 없다. sleep을 사용하지 않고 Event barrier로 종료 시점을 고정했다.

첫 검증 스크립트는 종료된 자식이 기다리던 Event에 finally에서 set을 호출해 대기했다. 해당 검증 프로세스2개만 종료하고, 강제 종료된 자식의 동기화 객체를 재사용하지 않도록 정리 코드를 수정했다. 두 초기 실행은 통과 결과에 포함하지 않는다. 최종 검증의 자식과 부모는 종료됐다.

이 인수는 일반 임시 vault의 전체 배치 경로다. standalone ingest/compile 호출에서 이전 batch를 정리하는 기능이나 관리형 staging publication 전 강제 종료의 시작 기록 보존까지 구현한 것은 아니다. 읽기 상태의 running 기록 자체를 프로세스 생존 증거로 사용하지 않는다. managed 세대 crash/복구·최신 설치 반영·실제 업무 공유·운영 및 M1–M14는 남는다.
