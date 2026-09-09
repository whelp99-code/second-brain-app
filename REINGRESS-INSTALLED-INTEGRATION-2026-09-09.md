# 최신 설치 후보 자비스 연동 — 2026-09-09

제품 e6866b0까지의 수정으로 설치 후보를 새로 만들었다. git archive 기반 wheel이므로 사용자 미추적 파일은 포함하지 않는다. reingress.py/ops.py/compile.py의 설치 바이트가 해당 커밋 원문과 같음을 확인했다.

후보: `/var/tmp/sb-reingress-candidate-od1trd1c/releases/95637d2efe27899689c2a90b3eeef5edc10022aa`

자비스 후보: `/var/tmp/jarvis-locked-candidate-j9w0jrk8/source/dist`

검증 결과:

- 현재 개발 소스의 실제 TLS/gateway/MCP/CLI 통합 4경로 통과.
- 소스 sb 디렉터리 없는 임시 harness에서 설치된 provider를 import한 동일 4경로 통과.
- 정상 요청: provider proved → 자비스 settled → control completed, 새 reader 로그인 및 독립 stdio 클라이언트 2개 각각 2기록 회수. 완료 처리 1회/시도 1회, 같은 generation 확인, reader 철회 후 403.
- 접수 중 철회는 거부되고, 접수 후 실행 전 철회/만료는 실패 상태·미활성 세대로 남는다. 4경로 모두 FK 오류 0.
- 설치된 실제 MCP 실행 파일의 read-v2/read-v5/status-v1/write-v1 초기화와 도구 목록 4프로파일 통과.

실행 도구: deploy/check-release-integration.py 및 uv run python deploy/check-release-mcp.py. 초기 시스템 Python에는 MCP 모듈이 없어 시작하지 못했으며 프로젝트 가상환경으로 정상 실행했다.

검증 한계: 전달 사용자 identity·원본·정책·시각·검증 작업은 fixture다. native 모델 호출은 이번 검증에서 0회다. 삭제 중단 회귀는 직전 30개 검사에서 검증됐으며 이 통합 4경로 자체가 모든 삭제 시나리오를 실행하지는 않는다. 운영 활성화·인증 재로그인·DB 전환·전체 M1–M14 인수 완료가 아니다.

운영 서비스/설정/current는 변경하지 않았다. 최신 후보를 준비하여 이후 운영 전환 인수에 사용할 수 있는 상태로 유지한다.
