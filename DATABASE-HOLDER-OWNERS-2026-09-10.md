# 운영 DB 사용자의 서비스 소속 식별

기준ab490b7. 실제 DB 핸들 보유 PID1625716/2123274를 /proc comm/exe/cwd/cgroup 및 systemctl show의 MainPID로 대조했다. 각각 jm-jarvis-dashboard.service와 jm-jarvis.service였다. 두 service 모두 active/running, Restart=always, KillMode=control-group, TimeoutStopUSec=90초, PartOf/TriggeredBy 비어 있음. dashboard 작업 디렉터리는 artifact-4146a192... 릴리스, authority는 a3cbbbe... 릴리스다. 한 서비스만 정지해 다른 서비스의 DB 핸들까지 닫힌다고 가정할 수 없다. systemctl로 명시적 stop을 수행한 경우의 Restart=always 의미와 단순 PID kill을 구분하며 이번에는 둘 다 수행하지 않았다.

check-database-handles.py 출력에 holder_processes를 추가했다. 실제 fd/mmap에서 발견한 PID만 중복 제거해 comm/cgroup을 보고한다. 명령 인수·환경 변수는 읽지 않는다. 이미 종료된 프로세스와 권한 부족은 명시 문자열로 남기며 소유자를 꾸며내지 않는다. 같은 순간의 소유 관측이며 PID 재사용·미래 실행 배제를 보장하지 않는다.

관련12통과/1.75초·Ruff/diff 통과. 실제 별도 CLI 재관측 exit2에서 위 서비스2개와 관측불가17개, drain_authorized=false를 확인했다. 원시 지역 결과 /var/tmp/sb-database-owners-20260910.json. 종료 핸들/맵 전용 검사와 프로세스 소멸 회귀도 포함한다.

운영 전환 순서의 선행 조건을 구체화했다: 두 서비스와 관련 scheduler의 새 DB 접근 중단 조율, 진행 중 작업/불확실 outbox 확인, 종료 후 재관측 및 권한 부족 범위 해소, 백업/DB migration/rollback 호환성 인수, paired 실행물 전환, 두 서비스 재시작·실제 업무 확인. 이 목록은 이번에 실행한 작업이 아니다. 현재는 관측불가가 남아 운영 전환 보류이며 프로세스를 임의 종료하지 않았다.

운영 DB/서비스·타 리포 변경 또는 push 없음. provider 제품 코드는 미변경, 배포 관측 도구 개선이다. 실제업무·공통 기억 운영과 전체 M1–M14 미완료.
