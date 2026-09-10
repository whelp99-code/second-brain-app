# OpenCode SQLite 읽기 예산과 실패 복구

기존 참조 SQLite는 `fetchall()`로 모든 행을 읽고, 오류는 빈 결과로 숨겼다. 내용 변경 감지를 위해 매 scan에서 DB를 읽게 된 현재 구현에서 보강이 필요한 경로다.

수정: snapshot당 DB 파일 64 MiB, 반환 항목 최대 5,000행, 반환 필드 누적 64 MiB, SQLite VM 명령 1,000,000개를 상한으로 둔다. 파일 크기 검사는 열기 전, SQL 값/행 크기는 SQLite length limit, 행 수는 LIMIT 5001과 순차 반환 검사, 누적 크기는 Python에서 검사한다. progress handler는 기본 1,000명령마다 실행하여 쿼리를 중단한다. 연결은 정상/실패 모두 finally에서 닫는다. 64 MiB/5,000행은 기존 파일/DB 기본 예산에 맞춘 snapshot별 고정 상한이며 `[caps] max_db_rows_per_run` 설정을 읽거나 실행 전체 한도를 구현한 것은 아니다.

한도 초과는 `database-limit`, 손상/누락 등 읽기 오류는 `unreadable-session-file`로 보고한다. 부분 결과를 성공 처리하지 않고 이전 커서를 보존한다. 정상 형제 파일은 계속 수집한다. 권한 없는 삭제/원문 변경 없이 입력의 적정 export 분할로 다시 수집할 수 있다.

검증:
- 수정 전 실제 DB 테스트에서 제한 세 종류가 적용되지 않고 결과를 모두 내보냈으며, 손상 DB는 빈 결과가 되어 네 테스트가 실패했다. 최초 테스트 작성 때 신규 상수 부재 오류가 나서 monkeypatch가 상수를 주입하도록 고친 뒤 이 행동 실패를 재확인했다.
- 수정 후 파일/행/실행량 제한, 작은 DB view가 반환값을 확대하여 누적 예산 초과, 성공 커서 보존·재시도·부분 결과 배제를 검증했다.
- 관련 OpenCode/세션/파일 교체 **62 passed / 0.72초**, Ruff sb/tests 통과, 변경 모듈 basedpyright 0 errors / 0 warnings.
- 실제 격리 CLI: `init` 후 `ingest` 3회 모두 exit 0. 5,001행 DB는 사유만 기록·DB 항목 부분 수집 0, 형제 JSON 정상 수집. 테스트 DB를 1행으로 줄인 후 동일 snapshot 재시도에서 원장/CAS 본문 확인. 재실행 원장 불변.
- 결과 원본 `OPENCODE-DATABASE-LIMITS-2026-09-10.json`, 격리 경로 `/var/tmp/sb-opencode-db-limit-oit4y_65`. 최초 스크립트는 읽기 전용 원장 연결을 닫지 않아 다음 ingest가 GENERATION_READER_DRAIN_REQUIRED로 거부됐다. 검사 연결을 명시적으로 닫은 새 격리 환경에서 통과했다. 제품 검사 우회 없음.

한계: 이 예산은 전체 프로세스 RSS나 벽시계 시간의 엄격한 상한이 아니다. SQLite 내부 정렬/표현식 처리와 JSON 객체 확장 비용은 별개이며, 여러 snapshot의 배치 누적도 남는다. 파일 경로 검사 뒤 교체와 읽는 중 일반 파일 변경의 일관성·다중 root 상대 경로 충돌도 미완이다. 큰 DB를 자동 일부 수집하는 것은 보류하며 명시적 제한으로 실패시킨다. 실제 native OpenCode 연동 및 운영 배포는 이번 합성 DB 기반 CLI 검사로 대체하지 않는다. 전체 회귀/설치 paired 인수는 이번 수정 뒤 재실행하지 않았다.
