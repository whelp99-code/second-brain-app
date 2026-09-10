# 수집 실패 후 성공한 단계가 전체 실패를 숨기지 않는지 검증

현재 제품7a57eef의 SOURCE_READ_INCOMPLETE가 전체 배치에서도 유지되는지 실제 프로세스/HTTP로 검사했다. 신규 회귀 tests/integration/test_read_failure_batch_status.py는 임시 OpenCode export에64 MiB+1 byte sparse snapshot을 만들고 sb run을 별도 프로세스로 두 번 실행한다.

두 실행 모두:
- 수집은 size-limit 때문에 실패하며 SOURCE_READ_INCOMPLETE를 stderr에 출력하고 CLI 종료 코드1.
- 이후 입력 단위가 없는 compile 단계는 정상 완료되어 last_run.status는ok.
- 별도 sb status --json에서 last_batch.status=failed, errors=1, recent_stages의 ingest에size-limit 사유가 남음.
- 실제 로컬 HTTP /api/status도 같은 last_batch 실패/오류수와 요약의failed를 반환함.

결과: **1 passed / 3.70초**, 캐시 없는 전체 sb/tests Ruff 통과. 이 테스트의 두 번 실행은 코드상의 반복이며 두 개 테스트라고 집계하지 않는다. 빈 컴파일 경로이며 실제 모델 호출·native 앱·GUI 클릭 인수는 아니다.

기존 _choose_batch_outcome 및 영속 batch 상태가 수집 실패를 올바르게 유지했다. 제품 코드는 추가로 변경하지 않았고 회귀 검증을 추가했다. last_run은 마지막 개별 단계, last_batch는 전체 배치라는 기존 구분을 유지한다. last_run만으로 전체 완료를 판단하면 안 된다.

전체1,767통과 및 설치 인수는13cab77 기준, 최근 DB/JSON 파서/실패 상태 기능 변경은 집중·CLI 검증 기준이다. 운영 배포·실제 사용자 업무·M1–M14 전체 인수는 미완료다.
