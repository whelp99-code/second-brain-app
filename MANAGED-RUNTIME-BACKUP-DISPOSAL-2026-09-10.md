# 실제 런타임 관리 백업의 삭제 처분

기준a50d906. 외부 보존 사본 재유입 검사와 분리해 backup_root 내부에서 실제 backup_runtime이 만든 아카이브의 처분을 검증했다. 기존 restore_fixture의 원본 기억 생성 후 effect 요청 수락 직전에 실제 백업을 만든다. tar 내부 .recovery/requests/journal.db 존재와 삭제 대상 원문 포함을 직접 확인한다.

같은 관리 폴더에 별도 격리 provider의 무관한 기억으로 생성한 두 번째 유효 runtime 아카이브도 둔다. 기존 실제 signed forget 요청을 수락·실행한 뒤 proved 상태/삭제 순번1, 대상 아카이브 부재, 무관한 아카이브의 전체 bytes 동일, 남은 폴더 파일에서 대상 원문 부재를 확인했다. 관리형 사본을 전부 지워 통과하는 검사가 아니다.

처음 일반 operator-note.txt를 함께 두자 기존 validate_managed_backups가 UNMANIFESTED_BACKUP으로 삭제 완료를 거부했다. 잘못된 fixture였고 제품 무결성 규칙을 완화하지 않았다. 유효한 두 runtime 아카이브로 수정한 뒤 runtime 검사2통과/3.58초, managed manifest 관련 포함최종23통과/7.57초. Ruff sb/tests와 diff 통과. 제품 변경 없음.

이 검사는 실제 라이브러리·SQLite·tar·effect executor 경로이며 날짜/키/기억은 합성 fixture다. 사용자 운영 backup_root를 검사/삭제한 것은 아니다. 외부 사본 재유입, native cache/WAL/session 전체 삭제 수명 및 원장소실 DR를 대신하지 않는다. 운영 전환은 별도 보류 조건을 유지하고 전체 M1–M14 미완료, push 없음.
