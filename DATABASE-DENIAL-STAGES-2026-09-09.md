# 운영 DB 관측의 접근 거부 단계

check-database-handles.py의 unreadable_processes에 denied_resources를 추가했습니다. process_metadata/fd_directory/fd_target/maps를 구분해 프로세스 식별·FD목록·FD대상·메모리 매핑 중 어디서 권한이 거부됐는지 알 수 있습니다. 프로세스 인자나 환경변수는 읽거나 출력하지 않습니다. 기존 unreadable_pids 및 exit2/전환불가 판정은 유지합니다.

회귀: FD목록/FD대상/maps 권한 거부3사례를 주입해 진단 필드를 확인했습니다. 수정 전 필드 부재3실패, 수정 후 기존 실제 SQLite FD·mmap·파일 교체 검사 포함8 passed(1.42초), 변경 도구와 테스트 Ruff 통과입니다.

운영 읽기 전용 재실행은 exit2입니다. 접근 불가17개 중16개는 fd_directory, 나머지1개는 fd_target과maps가 거부됐습니다. 두 단계가 같은PID에서 거부되므로 단계 합계18을 프로세스18개로 해석하지 않습니다. 관측된 DB 핸들은 여전히6개입니다. 이 결과로 해당 프로세스가 DB를 사용하지 않는다고 판단할 수 없습니다. 필요한 후속 조치는 권한이 있는 운영 관측과 재기동/미래 열기 차단 범위 확정이며 이번에 권한이나 서비스를 변경하지 않았습니다.
