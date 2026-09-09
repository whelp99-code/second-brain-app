# 복구 대상별 상호 배제 — 2026-09-09

restore_backup의 staging은 고유하지만 같은 최종 대상에 대한 두 복구의 교체 순서는 보호되지 않았다. 대상 디렉터리 내부 잠금은 rename 후 다른 inode로 분리될 수 있어 부모 디렉터리의 대상명 해시별 잠금을 추가했다.

복구 검증·추출·게시·예외 복귀 전체를 LOCK_EX|LOCK_NB로 보호한다. 같은 대상은 RESTORE_DESTINATION_BUSY로 즉시 거부하며 다른 대상은 독립적으로 복구할 수 있다. 잠금 파일은 0600으로 생성하고 symlink를 따라가지 않으며 일반 파일·소유자·링크 수·권한을 검사한다. 잠금 파일은 해제 후 삭제하지 않는다. 대기자가 이미 연 파일과 새 파일로 잠금이 갈라지는 것을 막기 위해서다. FD를 닫아 잠금을 해제한다.

검증:

- 새 잠금·ops·CLI **68 passed/6.51초**. 별도 실제 Python 프로세스의 restore 요청이 busy로 거절되고 원래 내용/staging이 보존됨을 확인했다. 다른 대상 복구 성공, 잠금 해제 후 같은 대상 복구 성공·previous 보존 확인.
- 대상 rename 중 두 번째 잠금 거부, 예외 해제 후 재획득, 하드링크 잠금 거부 확인.
- restore/readiness/managed backup/backup cancellation **45 passed/13.91초**. 두 실행의 테스트 파일은 겹치지 않는다.
- Ruff sb/tests·diff check 통과. ops 정적 검사 오류0, 기존 문자열 결합/private 접근 경고2 유지.

운영 서비스/DB 변경 없음. 이 잠금은 같은 helper를 쓰는 협력적 복구 요청 간 상호 배제다. 일반 pipeline 작성자·외부 직접 파일 쓰기·잠금 파일의 외부 교체·중첩 대상 경로 충돌을 전부 직렬화하지 않는다. 운영 작성자를 정지하지 않은 in-place restore를 허용하는 근거로 사용하지 않는다. 강제 종료 후 두 번의 rename 사이에서 복구하는 영속 journal도 별도 과제다.
