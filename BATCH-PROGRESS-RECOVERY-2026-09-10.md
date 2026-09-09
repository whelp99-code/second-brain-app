# 단계 완료 진행 상태와 중단 후 계보 보존

배치 시작에는 running/0건만 기록하고 마지막에 전체 결과를 저장했기 때문에, 중간 강제 종료 시 이미 끝난 단계의 배치 수준 연결 정보가 없었다. 중단 판정은 detail을 고정 문자열로 덮어썼다.

단계가 반환될 때마다 같은 작성자 잠금 안에서 batch의 완료 단계 목록/ID/상태, 알려진 작성·오류 합계를 저장한다. 다음 배치에서 이전 running을 interrupted로 판정할 때 기존 detail을 보존하고, detail이 없을 때만 중단 설명을 넣는다. 배치 외곽 예외도 이미 완료된 단계 연결을 함께 저장한다. 기존 단계 원장은 변경하지 않는다.

진행 중인 단계가 반환하지 않았으면 그 단계의 미확정 작성·오류 수는 합계에 넣지 않는다. 따라서 중간 배치의 수치는 완료된 단계에 대한 확인된 진행량이다. finished_at은 interrupted의 실제 종료 순간이 아니라 다음 실행에서 중단을 확인한 시각이라는 기존 의미를 유지한다.

검증: ordinary/managed crash, run_all, runtime reliability, ops **40 passed / 6.85초**, 외곽 예외 기록 변경 후 run_all/ordinary crash **10 passed / 0.96초**(중복 포함). Ruff/diff 통과. 기존 테스트에 ingest 완료 전/후 두 강제 종료 시점을 넣었다.

별도 실제 자식 프로세스에서 ingest partial/errors1 이후 compile barrier에서 SIGKILL했다. 다음 배치가 잠금을 얻은 뒤 이전 행은 interrupted/완료 단계1/오류1, detail에는 실제 ingest ID/partial이 보존됐고 새 행은 ok/2단계/오류0이었다. [실제 원장 결과](BATCH-PROGRESS-RECOVERY-2026-09-10.json). 단계 결과는 합성이며 파일·SQLite·잠금·프로세스 종료를 mock하지 않았다. 검증 프로세스는 종료됐다.

관리형 publication 이전의 staged 이력은 active에 아직 공개되지 않는 기존 경계를 유지한다. 별도 영속 실행 감사·모든 종료 위치/외부 효과·최신 설치·실제 업무 공유·운영 및 M1–M14는 남는다.
