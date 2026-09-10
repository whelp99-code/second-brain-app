# 유지보수 검사 CLI 정리와 운영 상태 재관측

`deploy/check-release-maintenance.py --help`가 도움말 대신 `--help`를 디렉터리로 해석해 FileNotFoundError traceback을 출력했다. 인자 파서를 추가하고 설치 Python 실행 파일 존재·실행 가능 여부를 검사하도록 수정했다. 검사 본체의 강제 종료/복구/기억 보존 계약은 유지했다.

실제 CLI 검사: 도움말 exit0, 인자 누락/빈 디렉터리/없는 경로 각각 exit2, traceback 없음. Ruff와 diff 통과. 최신 f0fec14 설치 후보를 올바른 인자로 전달한 실제 유지보수 검사는 exit0: worker SIGKILL(-9), 정리1, 반복정리0, 독립 프로세스 기억 보존3회. 결과 `/var/tmp/sb-maintenance-cli-20260910.json`.

같은 작업에서 운영 DB를 읽기 전용으로 재관측했다. pending snapshot UTC `2026-09-10T00:28:40.969835+00:00`: 명시한 큐6개 비어 있음, active cursor0, 유효 GJC lease1, microloop lease0. 별도 /proc 관측은 PID1625716 dashboard와 PID2123274 authority가 DB/WAL/SHM을 사용함을 확인했고, 관측 불가 PID22개·대상 identity 변경 없음·exit2였다. 두 관측은 하나의 원자적 runtime snapshot이 아니며 lease는 프로세스 생존 증명이 아니다.

운영 전환은 보류한다. 큐가 비었다는 사실은 기존 writer 배제나 안전한 drain을 입증하지 않는다. 서비스·DB·current 링크를 변경하지 않았다. 이 보류와 별개로 설치 후보의 동작 검증과 도구 수정은 완료했으며 전체 M1–M14 목표는 유지한다.
