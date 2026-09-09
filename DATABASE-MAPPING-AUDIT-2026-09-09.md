# 운영 DB 메모리 매핑 관측 — 2026-09-09

파일 descriptor만 보는 검사에 /proc/PID/maps의 장치 번호와 inode 대조를 추가했다. 주소·프로세스 인수·메모리 내용은 출력하지 않는다. 같은 프로세스의 중복 매핑은 파일별로 묶는다. 읽기 불가 maps도 불완전 PID에 포함하고 열린 descriptor 또는 mapping이 있으면 관측 통과로 표시하지 않는다.

실제 libc mmap으로 임시 파일을 매핑한 후 fd를 닫고, 별도 검사 프로세스로 관측했다. 수정 전에는 open_handles가 비어 있고 mapped_files가 없어 회귀가 실패했다. 수정 후 mapped_files에서 부모 PID를 확인했다. 기존 SQLite 연결/종료 검사 포함 2 passed / 0.68초, Ruff 통과.

운영 DB를 새 검사로 읽기 전용 조사한 결과는 동명 JSON에 보존했다. /proc snapshot이며 검사 뒤 새로운 open을 막지 않는다. 다른 UID·이미 교체된 inode·원격 연결 및 접근 불가 프로세스 범위는 여전히 남는다. drain_authorized=false는 유지하며 프로세스 종료/운영 변경을 수행하지 않았다.
