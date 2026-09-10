# 재시도할 읽기 실패를 정상 완료로 숨기지 않기

문제: size-limit/database-limit/unstable-session-file/unreadable-session-file이 skip 메타데이터로 전달되면 pipeline이 일반 격리 항목처럼 저장하고 오류0·상태ok를 기록했다. 이전 skip SourceRef가 원장에 있으면 dedup에 의해 반복 실행에서도 문제가 숨겨졌다. 정상 파일이 함께 있어도 전체 수집의 완료 여부를 사용자가 잘못 판단할 수 있었다.

수정: 네 사유를 기존 중복 검사보다 먼저 확인한다. 실행의 시도/오류에 반영하고 SOURCE_READ_INCOMPLETE: source-id: reason을 기존 StageReport.failure·run_stage.detail에 기록한다. 해당 adapter의 커서는 전진시키지 않으며 정상 파일은 계속 처리·저장한다. 이미 정상 저장된 원문은 다음 실행에서 기존 중복 제거를 사용한다. 실패 항목은 성공 source_item으로 새로 기록하지 않는다. 과거 skip 행을 삭제하거나 source ID를 재작성하지 않았다. 입력 시도 예산도 적용한다.

일반 malformed 입력이나 live-store 등 모든 격리를 실행 실패로 바꾼 것은 아니다. 이번 분류는 위 네 가지 재시도 가능한 읽기 실패에 한정된다. 한 실행에 여러 실패가 있으면 오류 수를 집계하고 대표 사유 하나를 남기는 기존 failure 계약을 따른다.

검증:
- 네 사유 × 과거 skip 행 유무의 8개 회귀가 수정 전 오류0/ok로 실패했다. 수정 후 두 번 연속 실패 보고·이전 cursor 보존·정상 형제1개만 보존·복구 후 완료를 검증했다. 과거 skip 행은 초기 legacy 동작을 모사해 실제 원장에 먼저 기록했다.
- 수집/예산/선택/ack/HTTP 상태 pin/준비 상태/walking-skeleton **45 passed / 20.11초**.
- 캐시 없는 전체 Ruff 통과. pipeline basedpyright는 0 errors, 기존 registry.put 결과 미사용 경고1개로 exit1; 이번 추가 분기의 타입 경고는 없다.
- 실제 CLI init 후5,001행 DB+정상 JSON 수집: exit1, stderr SOURCE_READ_INCOMPLETE, 정상 형제 CAS/원장 저장. 별도 status --json에 failed/errors1/사유 보존.
- 같은 실패 상태에서 실제 로컬 HTTP /api/status가 200 응답으로 last_run_status=failed 및 recent_stages 오류1/사유를 제공했다. failures.total은 파생 작업 실패 집계이므로0이며 수집 실패는 recent_stages에 표현된다. GUI 클릭/화면 전체 인수는 아니다.
- DB를1행으로 복구한 뒤 CLI exit0·원문 수집, 다시 실행해도 원장 불변. 격리 환경 /var/tmp/sb-read-failure-cli-mm90yljh, 원본 INGEST-READ-FAILURE-STATUS-2026-09-10.json.

동작 변경: 과거 한도 초과/읽기 실패에도 exit0을 기대하던 호출자는 이제 비정상 종료를 받는다. 자동 재시도에서는 원본 복구·분할·권한 확인 등 사유 해결이 필요하다. 운영 배포는 하지 않았다. 과거 OpenCode DB 한도 시험의 exit0 기록은 당시 동작이며, 현재 상태는 본 보고서가 우선한다. 최신 전체1,767통과/설치 인수는13cab77 기준으로 이번 변경 이전이다. 전체 M1–M14와 실제 업무/각 native 제품/운영 인수는 유지한다.
