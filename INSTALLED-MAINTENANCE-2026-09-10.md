# 설치 후보 유지관리 인수와 운영 차이

운영 읽기 전용 관측: jm-second-brain-maintenance.timer active, service 마지막 2026-09-10 03:00 KST exit0. 실행 명령은 sb maintain --once이며 복원 workspace 옵션 없음. 실제 sb는 release41f0751aca8906d612961e704bc60dd0855fdabd를 가리킨다. 운영 설정에는 restore_workspace가 없으며 개발본의 새 옵션 연결은 적용되지 않았다. oneshot service inactive를 장애로 판정하지 않는다.

최신 제품 eea2c23e4d19b0da425a81934b4b510f691706c8을 git archive로 고정해 offline release 준비 exit0. 후보는 /var/tmp/sb-maintenance-release-7aycjs7i/releases/8b25969e345af2b11fef8ab60272a0100c5e859c. wheel SHA256 1a01c882119d04f133a4181cceab350638f95be1ce2464044f5d53d7924e4f1e. 운영 current와 연결하지 않았다.

새 deploy/check-release-maintenance.py는 후보의 독립 Python 및 bin/sb를 사용한다. 격리 config/vault에서 초기 기억 생성, 별도 worker가 잠금을 잡고 원문 작성, CLI busy/원문 보존, SIGKILL=-9, CLI 정리1건/폴더 비움, 재실행0건을 확인했다. 정상 종료 exit0. 소스 트리 import 대신 -I와 임시 cwd로 설치된 제품을 검사한다. 내용은 합성 자료다.

기존 check-release-mcp.py로 설치물 별도 stdio 네 프로필(read v2/v5, request status/write v1) 초기화와 정확한 도구 목록도 통과했다. 이 검사는 각 도구의 운영 권한·업무 실행까지 증명하지 않는다. [구조화 결과와 manifest](INSTALLED-MAINTENANCE-2026-09-10.json).

Ruff sb/tests/새 검증 스크립트 및 diff 통과. 제품 수정 없이 설치 인수 도구·보고만 추가했다. 직전 관련26통과와 전체 f45a1a1의1698통과를 유지하되 후보 eea2c23 전체 재검증으로 확대하지 않는다.

운영 타이머 경로 연결과 서비스 전환은 실제 복원 경로 식별, 구버전 writer 종료, SB/JARVIS paired 계약·DB 전환 및 rollback 인수 이후 진행한다. 현재 운영값만으로 미사용 복원 폴더를 추측해 삭제하지 않는다. 운영 서비스·DB·타 리포 변경과 push 없음. 실제 업무·다중 모델·원장소실 DR 및 전체 M1–M14 미완료.
