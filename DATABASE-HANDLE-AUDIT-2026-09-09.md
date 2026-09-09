# 운영 DB 열린 핸들 조사 — 2026-09-09

새 읽기 전용 도구 deploy/check-database-handles.py는 지정 SQLite DB와 현재 존재하는 -wal/-shm/-journal의 inode를 동일 UID /proc/*/fd에서 찾는다. 프로세스 인수·DB 내용은 출력하지 않는다. 핸들 존재는 exit1, 접근 불가 프로세스 존재는 exit2, 해당 관측에서 둘 다 없을 때만 exit0이다. 모든 응답에서 drain_authorized=false를 유지한다.

실제 실행: python deploy/check-database-handles.py /home/jm/.local/state/orca-jarvis/jarvis.sqlite — exit2. 384개 프로세스를 열거했고 접근 불가 PID 43개가 남았다. 접근 가능한 범위에서 3개 프로세스가 각각 DB/WAL/SHM을 열어 총9개 핸들이 확인됐다.

- PID1553366: session-73884.scope. 기존 명명된 서비스 목록에 직접 대응하지 않는 로그인 세션 프로세스다.
- PID1625716: jm-jarvis-dashboard.service.
- PID2123274: jm-jarvis.service.

따라서 명명된 systemd 서비스만 멈춘 상태를 DB 전환 완료 조건으로 사용하면 안 된다. 로그인 세션 프로세스의 담당 기능과 종료/재개 경로 확인이 추가로 필요하다. PID는 시점 관측이며 재사용될 수 있으므로 미래 종료 대상으로 저장하지 않는다. 이번에는 어떤 프로세스도 종료하지 않았다.

검증: 실제 SQLite WAL 연결을 연 부모를 별도 검사 프로세스에서 관측하고 연결 종료 후 사라짐을 확인하는 테스트 1개 통과(0.31초), Ruff 통과. 처음 테스트는 접근 불가 프로세스가 없다고 가정해 실패했다. 이를 검사기의 실제 불완전 상태와 대조하도록 수정했고, 열린 테스트 DB의 관측 자체는 그대로 필수다.

한계: 같은 UID·현재 inode의 일시적 관측이다. 다른 사용자, 이미 교체된 inode, 메모리 매핑만 남은 파일, 네트워크 클라이언트, 검사 후 신규 open, procfs 읽기 권한 한계를 포함하지 못한다. 자동 배포 허가로 사용하지 않는다. 운영 파일/서비스/설정 변경 없음, 전체 운영 전환 인수는 미완료.
