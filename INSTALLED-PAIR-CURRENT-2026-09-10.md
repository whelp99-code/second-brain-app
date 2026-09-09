# 최신 설치 provider와 자비스 연동 인수

현재 JARVIS 소스 HEAD195b1a7이 기존 격리 빌드 기준과 동일함을 확인했다. SB는 제품 eea2c23 설치 후보8b25969e345af2b11fef8ab60272a0100c5e859c를 사용했다. 이후 작업의 변경은 평가/검증 도구와 보고이며 이 후보의 제품 코드 범위를 명시한다.

기존 deploy/check-release-integration.py로 설치 provider + /var/tmp/jarvis-current-pair-_mq15nmd/source/dist 조합을 실행했다. 후보 source_commit에 맞는 scripts/tests/contracts만 임시 harness에 복사하고 sb 소스는 제공하지 않았다. 실제 provider 모듈4개가 설치 .venv 내부에서 import되는지 확인했다.

결과 exit0:
- 실제 검증 TLS·별도 Python verifier·gateway session·공개 MCP write→CLI execute.
- 정상 요청 provider proved, JARVIS settled, control completed. 다른 reader agent의 fresh login에서2records, 독립 stdio client2개가 각각2records.
- 완료 재처리 후 settlements1/attempts1/FK errors0, 동일 세대 유지.
- 수락 도중 철회는 denied/accepted row 없음. 실행 전 철회 및 만료는 failed/새 활성 세대 없음. reader 철회는403.
- 모델 호출0. identity forwarder·source·정책·시계는 fixture.

[전체 결과·manifest·모듈 경로·내용 해시](INSTALLED-PAIR-CURRENT-2026-09-10.json). 실행 전후 provider18474항목/JARVIS19588항목의 전체 inventory와 실제 Node 실행파일 해시 불변 검사까지 통과해야 성공 보고를 출력한다. 따라서 MCP 도구 목록만의 확인보다 넓은 설치물 인수다. 이를 운영 current 활성화나 실제 사용자 업무 성공으로 표현하지 않는다.

재현: python deploy/check-release-integration.py /absolute/provider-release /absolute/jarvis-build/dist.

남는 운영 조건: 기존 worker 배제, 운영 DB 전환 및 rollback, 실제 인증 설정·복원 workspace 경로/서비스 쓰기 범위, 관리형 native 세션 수명·사용자 작업 계보. 이 설치 연동으로 해당 위험을 자동 해소하지 않는다. 운영 DB/서비스/current·타 리포 변경 없음, push 없음. 전체 M1–M14 미완료.
