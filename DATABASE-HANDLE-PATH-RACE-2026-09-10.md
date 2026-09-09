# DB 사용 관측의 심볼릭 링크 전환 누락 수정

기준23ed645. check-database-handles.py는 입력 경로를 처음 resolve한 뒤 그 경로만 재검사해, 검사 중 current.sqlite 링크가 다른 DB로 전환되어도 target_identity_changed=false를 반환했다. 테스트에서 실제 링크를 /proc 순회 시점에 바꿔 실패1개를 재현했다.

수정: 원래 absolute 입력 경로를 보존하고 순회 종료 때 strict resolve로 다시 확인한다. 해석 결과가 달라지거나 경로가 사라짐/접근 오류이면 기존 target_identity_changed를 true로 유지해 exit2의 불완전 관측으로 처리한다. resolved 파일/sidecar inode 변경 검사도 유지한다. 출력에 requested_database를 추가해 관측 대상과 사용자가 지정한 경로를 구분한다.

최종 관련11 passed/1.75초·Ruff 변경도구/검사·diff 통과. 기존 실제 별도 프로세스 SQLite/WAL 핸들 및 mmap-only 검사도 포함한다.

실제 운영 /home/jm/.local/state/orca-jarvis/jarvis.sqlite 관측 실행exit2. 원본 데이터 행/프로세스 인수는 읽거나 출력하지 않았다. 같은UID 프로세스327개를 순회했고 PID1625716과2123274에서 각각 DB/WAL/SHM fd 및 SHM 매핑을 관측했다. 읽지 못한 PID17개, target_identity_changed=false, drain_authorized=false. 원시 지역 결과 /var/tmp/sb-database-handles-20260910.json.

따라서 writer drain 완료로 해석하지 않는다. 관측된 fd가 현재 쓰기를 실행 중이라는 뜻도 아니지만 DB 전환 전 소유 실행기의 정지/재시작 조율이 필요하다. 권한 부족·다른UID·미래 open·관측 도중 열렸다 닫힌 핸들 전체는 여전히 보장 범위 밖이다. 이 도구는 drain 승인기가 아니며 현재 보고에도 false를 유지한다.

운영 DB/서비스 전환은 보류, 프로세스를 임의 종료하지 않았다. 제품 provider 코드는 미변경이고 배포 관측 도구만 수정했다. 실제업무·공통 기억 운영 및 전체 M1–M14는 미완료. push 없음.
