# OpenCode 참조 DB 변경과 활성 WAL 보류

문제: DB 결과 추출 후 같은 길이 갱신 또는 atomic replace가 발생해도 불안정한 읽기를 보고하지 않았다. 또한 기존 live-store 검사는 opencode.db-wal/shm 등의 고정 이름만 검사하여 custom-export.sqlite-wal처럼 실제 참조 파일명이 다른 경우 활성 WAL을 놓쳤다. immutable 읽기는 WAL에만 있는 변경을 반영하지 않아 이전 본문을 변경 없음으로 처리할 수 있었다.

수정: 공통 file_revision으로 DB 열기 전, 연결 후, 파싱 완료 후의 device/inode/size/mtime/ctime을 비교한다. 변경 시 unstable-session-file로 본문을 내보내지 않고 이전 커서를 유지한다. 실제 DB 경로에 붙는 -wal/-shm/-journal을 열기 전/연결 후/파싱 후 검사하고 존재하면 live-store로 보류한다. dangling symlink sidecar도 lexists로 감지한다. 원본 DB나 sidecar를 커넥터가 삭제·checkpoint하지 않는다. 기존 readonly immutable 연결과 finally close를 유지한다.

검증:
- 실제 같은 길이 SQL 갱신 및 다른 inode 교체 주입: 수정 전 2 failed → 수정 후 본문 배제·성공 커서 보존·최신 본문 재수집·재실행0 확인.
- 실제 WAL 연결을 열어 갱신한 custom-export.sqlite: 수정 전 조용히 빈 결과였으며 회귀 실패. 수정 후 live-store·커서 유지, 연결 종료로 checkpoint 후 최신 본문 재수집.
- 관련 테스트 **77 passed / 0.81초**, 전체 sb/tests Ruff 통과, 변경 모듈 basedpyright 0 errors / 0 warnings.
- 별도 실제 CLI: init와 ingest3회 모두 exit0. 최초 before 수집, WAL 활성 중 사유만 추가, 종료 후 after! 수집. 원장/CAS에 두 본문 보존. 결과 OPENCODE-DATABASE-STABILITY-2026-09-10.json, 격리 환경 /var/tmp/sb-opencode-wal-ut4jrppp.
- 이전 5,001행 제한·형제 수집·1행 복구 CLI도 /var/tmp/sb-opencode-db-limit-1mienjks에서 재통과했다.

한계: metadata 검사이며 SQLite가 여는 파일 descriptor 자체를 고정한 구현은 아니다. 경로 검사 사이 교체 후 원상복구, 상위 경로 변경, sidecar 생성·삭제가 검사 사이에 끝나는 모든 경우는 입증하지 않았다. 이 변경으로 경로 교체 공격 전체가 해결됐다고 주장하지 않는다. 실행 중인 DB 직접 수집은 보류하고 안정된 export를 대상으로 한다. 실제 native OpenCode 실행자의 export 연동 인수는 별도다.

최신 전체1,767통과와 설치물 인수는 13cab77 기준으로 이번 제품 변경 이전 결과다. 이번 수정 이후 전체 검사/설치 인수를 재실행하지 않았다. 운영 전환·실제 업무·전체 M1–M14는 미완료다.
