# 전체 배치 실행 상태 영속화

run_all은 단계별 원장만 기록하고 반환할 때 전체 결과를 선택했다. 이후 상태 조회는 마지막 단계만 알 수 있어 앞 단계 실패 뒤 compile/brief 성공을 전체 성공으로 오해할 수 있었다.

## 구현

기존 run_stage에 stage=batch 기록을 추가한다. 기존 단일 작성자 잠금 안에서 시작 running과 종료 상태를 기록하고 실제 실행한 단계 ID/상태, 선택된 반환 run ID, 오류 합계, 작성 합계를 보존한다. 생략한 brief를 실행 횟수나 오류에 중복 계산하지 않는다. 단계별 반환값과 기존 실패 우선순위는 유지한다. 새 스키마나 별도 DB는 도입하지 않았다.

관리형 경로는 기존 GenerationMutationService의 staged root에 같은 기록을 저장하고 기존 세대 publication을 따른다. ops.last_batch는 최근 batch를 별도로 반환한다. 웹은 최근 단계 상태와 최근 전체 배치 상태/오류를 함께 표시한다. 과거 기록에서 존재하지 않는 배치 관계를 추정하지 않는다.

예외 발생 시 실패와 완료 시각을 기록하고 다시 예외를 전달하며 잠금을 해제한다. 강제 종료가 남긴 running 기록은 생존 프로세스의 증거가 아니며 자동 복구/중단 판정은 이번에 구현하지 않았다. 관리형 세대가 publication 전에 강제 종료된 경우의 시작 기록 보존을 보장한 것도 아니다. 이를 전체 crash 인수 완료로 표현하지 않는다.

## 검증

최종 run_all/CLI/ops/web/runtime reliability/MCP generation **102 passed / 18.71초**, Ruff/diff 통과. 부분 실패 뒤 성공, 실제 두 단계/brief 생략, 원장 재열기, 선택 ID 계보, 예외 기록·잠금 해제를 검증했다.

실제 Claude로 만든 기억이 있는 관리형 임시 저장소에서 run_all을 실행했다. 처음에는 정상 완료를 예상했으나 ingest가 `SafeSourceFilesystemError: source mutation observed: .`로 실패했다. 뒤의 compile은 ok였다. 정상 완료 assert는 실패했으며 성공 인수로 기록하지 않는다.

이후 새 Python 프로세스와 실제 HTTP 서버에서 last_run=ok, last_batch=failed/errors1, 실제 시도2단계와 완료 시각을 확인했다. 웹 summary도 전체 배치 failed를 표시했다. 따라서 실패 배치의 영속 조회는 실제 실행으로 확인했다. 원본 변경 감지의 원인은 별도 조사 대상으로 유지한다. [원장·HTTP 증거](PERSISTED-BATCH-STATUS-2026-09-10.json). 임시 저장소·격리 registry 사용, 서버 종료, 운영 데이터 변경 없음.

최신 설치 후보는 이 변경 이전이다. 새 배치 기록의 전면 crash/복구 인수, 원본 변경 감지 원인, 최신 설치 반영, 운영 전환·실제 업무 공유·M1–M14는 남는다.
