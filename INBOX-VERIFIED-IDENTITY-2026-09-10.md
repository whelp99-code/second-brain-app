# 검증 완료 후 교체된 입력의 완료 처리 방지

`acknowledge`는 본문을 읽어 커밋된 source version과 일치하는지 확인했지만, `_move_done`은 그때 검증한 stat을 전달받지 않았다. 검증 직후 파일을 교체하거나 같은 inode의 본문을 바꾸면 이동 함수가 바뀐 파일을 새 기준으로 삼아 완료 처리했다. 두 결정적 파일 경합 테스트에서 오류 없이 새 입력이 제거되어 실패했다.

검증에 사용한 stat을 완료 함수에 전달하고, descriptor 기준으로 다시 읽은 dev/ino/mode/size/mtime_ns/ctime_ns와 비교하도록 수정했다. 다르면 명시적 OSError를 반환하므로 기존 pipeline 오류 보고 경로에 연결된다. 일반 파일 읽기에서도 같은 식별 함수를 사용한다. hard link 게시 후에는 게시 작업 자체가 ctime을 바꾸므로 ctime을 제외한 나머지 식별 정보를 다시 비교한다.

최종 검증은 inode 교체와 같은 inode 내용 변경 각각에서 오류, 새 본문의 inbox 유지, 빈 완료 폴더, 기존 cursor로 다음 scan 시 새 source version 1개 회수를 확인했다. inbox/완료 재시도/pending/실제 pipeline walking skeleton **27 passed / 4.52초**, Ruff sb/tests, 변경 모듈 basedpyright **0 errors / 0 warnings**, diff 검사 통과.

이번에 닫은 범위는 본문 검증과 완료 함수 진입 사이의 경합이다. 최종 stat과 unlink 사이의 비협조적 교체, 동일 inode 내용 변경 후 mtime 복구, 열린 writer·디렉터리 이동·전원 장애까지 모두 원자적으로 해결했다는 증거는 아니다. 그 범위를 보장하는 이동 방식으로 확대 선언하지 않는다. 운영 데이터·서비스는 변경하지 않았다. M1–M14 및 실제 운영 인수 목표는 유지한다.
