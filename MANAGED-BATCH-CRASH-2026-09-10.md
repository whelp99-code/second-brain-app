# 관리형 배치 publication 전 강제 종료 검증

관리형 임시 저장소에 기억 원본1건을 remember로 보존한 뒤, 별도 자식 프로세스에서 run_all을 실행했다. 실제 staged ingest 진입점에 Event barrier를 두고 SIGKILL했다. 시간 sleep으로 종료 시점을 추측하지 않았다.

확인한 조건:
- 자식 작성자가 살아 있을 때 두 번째 run_all은 already_running이며 active 포인터는 이전 세대다.
- staged batch의 시작 기록은 공개된 status_snapshot에 나타나지 않는다.
- 자식 강제 종료 후 active 포인터와 대기 inbox 원본 바이트는 그대로다.
- 다음 실제 run_all이 정상 종료하고 새 세대를 공개한다. 원본 바이트를 보존하고 last_batch=ok를 기록한다.
- 복구 후 vault-generations/.staging은 비어 있다.

관련 managed/ordinary batch crash, runtime reliability, MCP generation **10 passed / 7.40초**, Ruff/diff 통과. 별도 실행 스크립트에서도 같은 실제 프로세스 종료·원장·파일 검증을 반복했다. [실행 증거](MANAGED-BATCH-CRASH-2026-09-10.json). 최초 테스트의 staging 경로 오기를 고친 뒤 검사했으며 제품 복구 코드는 변경하지 않았다.

검증 입력은 합성 원본이다. 소스 목록은 명시적으로 비워 원본을 처리하지 않고 보존하는 복구를 검사했다. 단계 함수는 종료 위치 제어용이며 모델 호출·새 사실 생성·삭제/복원·공개 이후 종료 전체를 검증한 것은 아니다. 버려진 staged batch의 시작 이력은 active 원장에 보존되지 않는다는 경계를 확인했으며 영속 운영 감사 이력까지 완성됐다고 주장하지 않는다.

이번 커밋은 회귀 테스트와 증거를 추가한다. 실제 자식과 서버 외 운영 프로세스를 종료하지 않았고 공용 레지스트리·운영 데이터 변경 없음. 최신 설치 반영·실제 업무/다른 에이전트 공유·운영 및 전체 M1–M14는 남는다.
