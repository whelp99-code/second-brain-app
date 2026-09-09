# 외부 의존성 경로 없는 자비스 후보 — 2026-09-09

최신 JARVIS e6984ad 후보의 node_modules를 새 후보 내부로 복사했다. 기존 후보는 유지했다. 새 경로는 /var/tmp/jarvis-contained-candidate-k54z40zc/source이며 dist/node_modules 등32개 symlink는 모두 이 root 내부로 resolve된다. 외부 symlink 0개, broken symlink 없음. 단, Node 실행기와 시스템 라이브러리까지 포함한 독립 OS 이미지는 아니다.

잠금 파일 및 직접 runtime 의존성7개 일치 검사 통과. 새 경로의 better-sqlite3를 새 Node 프로세스로 로드하여 Node v24.19.0 / ABI137 / SQLite3.53.2 메모리 쿼리 통과. SB 최신 wheel 설치 후보와 실제 TLS/gateway/CLI/MCP 연동4경로 exit0. 정상 저장·완료·새 로그인·독립2클라이언트 조회 및 철회/만료 차단 유지.

모든 일반 파일 SHA256·mode 및 symlink 대상 목록을 후보 상위 contents.json에 저장했다. 파일 수와 inventory SHA256은 동명 저장소 JSON에 기록했다. 이 목록은 이번 시점 인벤토리이며 지속적인 변조 감시나 운영 봉인을 의미하지 않는다. 전체 전이 의존성의 공급망 검증을 수행했다는 주장도 아니다.

운영 current/서비스/DB/설정 변경 없음. SSH 구버전 DB 보유자, 관측 불가 범위, 롤백 호환성과 운영 구성 인수 등은 남는다. 기존 외부 후보 디렉터리 제거 없이 경로 검사와 실제 로드로 외부 symlink 의존이 없음을 확인했다.
