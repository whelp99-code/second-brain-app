# 복구 게시 실패 시 기존 경로 복원 — 2026-09-09

restore_backup은 기존 비어 있지 않은 대상 디렉터리를 previous로 옮긴 뒤 staging을 최종 위치로 rename한다. 두 번째 rename이 OSError로 실패하면 기존 경로가 사라진 채 반환하던 결함을 회귀 테스트로 재현했다.

최종 게시가 실패하면 기존 previous를 원래 위치로 돌려놓고 원래 오류를 다시 발생시킨다. 복귀도 실패하거나 다른 대상이 이미 나타난 경우에는 RESTORE_ROLLBACK_FAILED와 보존된 원본 위치를 반환한다. 관측된 새 대상을 덮어쓰지 않는다. 원본을 삭제하거나 실패를 성공으로 승격하지 않는다.

검증: ops/CLI **64 passed/6.20초**, Ruff sb/tests 및 diff check 통과. 게시 실패 후 원래 내용 복원, 복귀 실패 후 previous 보존, 새 대상이 생긴 경우 그 내용과 previous 동시 보존을 확인했다. 실제 별도 CLI restore --to 임시대상 --force도 exit0, 37파일 복원·wiki1페이지·기존 내용 previous 보존을 확인했다.

이 변경은 예외 처리 가능한 게시 실패에 한정된다. 전원 차단/프로세스 강제 종료, 동시에 복구하는 작성자, 존재 확인 이후의 교체 경합까지 원자적으로 해결하지 않는다. 운영 active generation 직접 복구 제한은 유지한다. 운영 DB/current/서비스를 변경하지 않았다.
