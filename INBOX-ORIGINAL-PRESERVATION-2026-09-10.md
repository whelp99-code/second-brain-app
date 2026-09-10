# 동일 이름 재수집 시 이전 원본 보존

기존 `_move_done`의 `os.replace`는 `.done/keep.md`가 있어도 새 원본으로 덮어썼다. 이전 원본을 유지해야 한다는 회귀 테스트가 실제 이전 본문 소실로 실패했다. CAS/원장의 원본 보존과 별개로 사용자가 수집 완료 폴더에서 이전 입력을 잃는 결함이다.

완료 파일을 같은 파일시스템의 hard link로 게시하여 존재하는 경로를 원자적으로 덮어쓰지 않도록 수정했다. 기본 파일명이 이미 다른 inode를 가리키면 상대 경로와 수집 version의 SHA-256으로 구분한 `version-<digest><suffix>`에 보관한다. 이 경로마저 다른 파일과 충돌하면 오류를 전달하고 원본을 제거하지 않는다. 디렉터리 descriptor와 O_NOFOLLOW 보호는 유지했다.

보존이 성공한 뒤 입력 파일을 제거한다. 두 동작 사이에 실패하면 기존 보관본과 입력이 같은 inode인지 확인하여 재시도하므로 동일 입력의 보관본이 반복 생성되지 않는다. 게시 전 원본이 일반 파일인지, 게시 후 보관본과 현재 입력이 같은 inode인지 검사한다. 이 절차를 모든 비협조적 writer와의 원자적인 exact-version 이동으로 주장하지 않는다. 마지막 검사와 unlink 사이의 경합, 열린 writer에 의한 동일 inode 내용 변경, 디렉터리 자체 이동 및 전원 장애 내구성의 전체 증명은 남는다. hard link를 지원하지 않는 파일시스템에서는 오류를 보고하고 입력을 유지하며 덮어쓰기 방식으로 우회하지 않는다.

검증:

- 동일 이름 이전 원본 덮어쓰기 실패 재현 → 이전/새 원본 모두 보존.
- 기본 경로와 이름 충돌 경로 각각 보존 직후 unlink 실패 주입 → 새 adapter가 기존 cursor로 재개하고 원장에 이미 반영된 refs를 acknowledge → 새 보관본 생성 없이 입력 정리.
- inbox/완료 실패 복구/pending/walking skeleton **25 passed / 4.34초**.
- Ruff 전체 sb/tests, 변경 모듈 basedpyright **0 errors / 0 warnings**, diff 검사 통과.
- 별도 실제 CLI 프로세스 2회로 같은 `note.md`에 서로 다른 본문을 수집: exit codes [0,0], 최초 이름의 이전 원본 유지, 보관 원본2개, 봉인 원장의 source version2개. `/var/tmp/sb-inbox-preservation-d7lw6jwt/result.json`.

격리된 합성 입력으로 실제 CLI 경로를 확인했으며 운영 데이터·서비스는 변경하지 않았다. 전체 회귀/설치물 재인수 및 M1–M14 전체 완료를 의미하지 않는다.
