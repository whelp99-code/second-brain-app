# 재유입 검증 불능과 정상 삭제 차단 구분

현재 pipeline은 ReingressGate의 모든 ErasureError를 삭제된 입력의 정상 차단처럼 취급했다. gate.check_content가 SQLITE_LIMIT_VARIABLE_NUMBER 부족으로 REINGRESS_QUERY_LIMIT_UNAVAILABLE를 내더라도 실행은 ok/errors0/exit0으로 남았다. 검증할 수 없는 상태가 정상 수집 완료로 보이는 문제다.

TOMBSTONE_REINGRESS_BLOCKED는 기존대로 차단한다. 다른 ErasureError는 REINGRESS_VERIFICATION_FAILED로 실패 기록·오류 집계한다. 원문 저장 전 검사이며 adapter cursor는 전진하지 않는다. 권한·삭제 검사 자체를 완화하지 않았고 예외 내용을 원문과 함께 노출하지 않는다.

회귀는 실제 ReingressGate DB의 SQLite 변수 한도를0으로 바꾸어 원래 check_content를 실행했다. 수정 전 exit0/ok로 실패, 수정 후 exit1/errors1/명시적 사유와 빈 source_items/cursors, 원문 보존을 확인했다. 한도를 복구한 다음 같은 파이프라인을 다시 실행하면 exit0/written1/원장1개로 수집된다. 테스트가 에러를 단순 대역 반환한 것은 아니지만, 실제 운영 장애를 발생시킨 것도 아니다.

검증: tests/test_ingest_reingress_failure.py, test_reingress.py, test_ingest_read_failures.py, integration/test_memory_restore_reingress.py **22 passed / 41.38초**. 캐시 없는 전체 sb/tests Ruff 및 diff 검사 통과. 기존 삭제/복원 재유입 차단 시나리오도 함께 통과했다. 별도 native 클라이언트나 운영 배포 인수는 이번에 수행하지 않았다.

기능 변경은 검증 불능의 실패 보고이며, 정상 tombstone 차단을 실행 오류로 바꾸지 않는다. 전체1,767통과/설치 인수는13cab77의 이전 결과다. 이후 변경 전체 재검증, 실제 업무·운영·M1–M14 전체 인수는 남는다.
