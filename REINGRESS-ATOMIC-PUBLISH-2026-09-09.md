# 삭제 차단 정보 원자 반영 — 2026-09-09

문제: ReingressGate의 SQLite 연결은 autocommit인데 block_targets가 executemany만 사용했다. source/content/citation/subject가 각각 커밋되어 다른 연결에서 0→1→2→3개의 중간 상태를 관측했다. 마지막 subject INSERT 실패 시 앞의 3개가 영구 잔류했다. 수정 전 회귀 테스트 2개가 이 두 조건으로 실패했다.

수정: 요청 대상 전체의 INSERT를 SAVEPOINT로 감쌌다. 성공하면 함께 반영하고 예외 발생 시 해당 묶음을 되돌린다. 기존 immutable trigger와 INSERT OR IGNORE 재실행 특성은 유지했다. 외부 트랜잭션이 있는 경우에도 이를 임의로 커밋하지 않는다.

검증:

- 별도 SQLite 연결은 저장 중 부분 결과를 보지 않는다.
- 마지막 식별자 저장 실패 후 새 행은 0개이고, 실패 제거 후 재실행은 성공한다.
- 별도 Python 프로세스를 두 번째 식별자 INSERT 직전 os._exit(73)으로 종료했다. DB 재개 후 integrity_check=ok, 기존 차단 행 보존, 중단 요청의 부분 행 0개를 확인했다. 재실행하면 네 식별자가 반영되고 원본 재유입이 차단된다.
- 관련 30 passed / 15.38초: test_reingress, test_erasure, integration/test_memory_restore_reingress, test_cancellation_result, test_provider_observations.
- uv run ruff check sb tests 통과. basedpyright sb/reingress.py 오류·경고 0.

한계: 단일 차단 DB의 반영 경계 검증이다. 파일 삭제·세대 활성화·자비스 완료 처리 전체가 하나의 트랜잭션이라는 의미는 아니다. 모든 물리 사본 삭제, 운영 릴리스 전환 및 실제 다른 모델 계열의 전체 인수는 여전히 남는다. 운영 DB/설정/서비스 변경 없음.
