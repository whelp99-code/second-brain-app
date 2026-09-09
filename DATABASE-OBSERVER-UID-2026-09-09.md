# 관리자 관측의 대상 UID 지정

현재 sudo -n id -u는 exit1, interactive authentication is required입니다. 관리자 관측이 실행 가능한 상태라고 가정하지 않았고, 인증·권한·서비스 설정을 변경하지 않았습니다.

기존 검사기는 os.getuid()의 프로세스만 조사하므로 관리자가 실행하면 root 프로세스만 검사할 수 있었습니다. --uid 옵션을 추가해 관측 대상UID를 지정하고 출력에 uid(대상)와 observer_uid(관측자)를 구분했습니다. 기본값은 이전과 같이 실행 사용자입니다. 선택한UID 외의 작성자나 미래 열기까지 제외했다는 주장은 하지 않으며 drain_authorized=false를 유지합니다.

운영자가 관리자 권한으로 확인할 때의 구체 명령은 다음과 같습니다. 이번 작업은 이 명령을 관리자 권한으로 실행하지 않았습니다.

```bash
sudo /usr/bin/python3 /home/jm/orca/projects/second-brain-app/deploy/check-database-handles.py --uid 1000 /home/jm/.local/state/orca-jarvis/jarvis.sqlite
```

검증: 관측자UID 반환값만 달리한 테스트에서도 실제 현재 프로세스의 열린 SQLite를 대상UID로 찾았습니다. 이는 관리자 권한 성공 검증이 아니라 UID선택 로직 검증입니다. 음수UID는 조사 전에 argparse exit2로 거부합니다. 기존FD/mmap/권한거부 검사 포함10 passed(1.59초), 변경 도구/테스트 Ruff통과입니다. 실제 일반사용자 --uid1000 관측은 exit2이며 기존 접근 불가 범위가 유지됐습니다. 운영 전환·서비스 중지 승인을 의미하지 않습니다.
