# 最新 설치 후보 조합 — 2026-09-09

이번 후보 조합은 SB ebe227c5c9f55a98407b3a908c5a935528254645 / JARVIS e6984add13a55ed6c31663f5217c7beac060d812다. 양쪽 git archive로 커밋을 고정했다. 최근 inbox 안전성·삭제 재유입·근거 부족 안내·portfolio stdin timeout을 포함한다.

- Provider: /var/tmp/memory-current-pair-6_l9twi9/provider/releases/7dc7c5bf67627751f56a47c35be8594eb7e11988
- JARVIS build: /var/tmp/memory-current-pair-6_l9twi9/jarvis/dist

Provider wheel 설치 완료. 자비스는 기존 locked candidate의 node_modules를 재사용했으며 잠금 파일/직접 runtime 의존성7개 일치 선검사, TypeScript emit, migration 복사를 통과했다. node_modules symlink가 있으므로 독립적인 봉인 운영 artifact로 간주하지 않는다.

검증: deploy/check-release-integration.py의 설치된 provider import와 새 자비스 빌드 간 실제 TLS/gateway/CLI/MCP4경로 exit0. 정상 저장 완료→새 reader 로그인→독립2클라이언트 회수 및 철회/만료 차단 통과. deploy/check-release-mcp.py에서 실제 설치 실행 파일 read-v2/read-v5/status-v1/write-v1 초기화·도구 목록4프로파일 통과. 이번 조합 검사는 native 모델 호출을 하지 않았다. 실제 원문/identity/시각/검증 작업은 fixture다.

이 조합을 후속 전환 리허설 기준으로 사용할 수 있다. 운영 current/서비스/DB/설정 변경 없음. SSH 구버전 DB 보유자·불완전 proc 관측·혼합 버전 rollback·실제 계정 운영·전체 M1–M14 인수는 남는다. 기존 개별 실측을 이번 조합에서 전부 재검증했다고 주장하지 않는다.
