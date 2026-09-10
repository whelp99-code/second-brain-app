# OpenCode snapshot 읽기 중 변경 감지

문제: JSON을 읽은 뒤 결과를 반환하기 전에 동일 길이 덮어쓰기 또는 atomic replace가 발생해도 이전 본문을 성공 처리했다. 실제 파일을 변경하는 두 회귀 테스트가 수정 전 실패했다.

수정: 공통 session_checkpoint.file_revision을 재사용하여 읽기 전후 device/inode/size/mtime_ns/ctime_ns를 비교한다. 다르면 본문을 버리고 unstable-session-file로 보고하며 기존 커서를 보존한다. 다음 scan에서 안정된 최신 파일을 다시 읽는다. lstat 기반 regular-file 확인도 재사용한다.

검증: 관련 OpenCode/세션/교체 테스트 64 passed / 0.72초, Ruff sb/tests 통과, 변경 모듈 basedpyright 0 errors / 0 warnings. 회귀는 같은 길이 덮어쓰기 및 다른 inode 교체, 본문 배제, 커서 0 유지, 새 원문 재수집, 변경 없는 재실행 0개를 검증한다. 정상 실제 CLI init+ingest 4회도 별도 임시 환경에서 재검증하여 서로 다른 원문 3개가 원장/CAS에 보존되고 네 번째 수집의 중복이 없음을 확인했다. 결과는 OPENCODE-SNAPSHOT-STABILITY-2026-09-10.json, 환경은 /var/tmp/sb-opencode-content-wcw1jvqp다.

한계: 읽기 중 교체는 테스트에서 실제 파일 조작을 정해진 지점에 주입한 결정적 검증이다. 실제 native OpenCode 프로세스의 동시 쓰기 인수는 아니다. 이 검사는 snapshot JSON에 적용되며 참조 SQLite의 경로 교체/읽는 중 변경, 상위 디렉터리 교체 및 변경 후 원상복구하는 모든 경우까지 입증하지 않는다. 최종 검사 이후 발생한 수정은 다음 scan에서 감지한다. 전체 회귀·설치 paired 인수는 이번 수정 뒤 재실행하지 않았다. M1–M14와 자비스 실제 운영 완료 기준은 유지한다.
