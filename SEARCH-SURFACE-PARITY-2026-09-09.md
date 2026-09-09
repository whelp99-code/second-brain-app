# CLI·웹·MCP 검색 설정 일치 인수

CLI는 기존 구현에서 명시적 registry_path를 전달하고 있어 제품 코드를 수정하지 않았다. 실제 Claude로 생성해 보관한 임시 vault와 명시적 레지스트리를 사용하고, 전역 레지스트리 환경값은 다른 임시 경로로 설정했다.

동일한 한글 검색어와 reference 범위로 독립 CLI subprocess, 실제 HTTP 서버, in-process MCP Client에서 검색했다. 각 결과2건의 page_id·knowledge_status·approval_status·verification 조합이 일치했다. 전역 검사 경로는 생성되지 않았다. 모델은 다시 호출하지 않았다. [세 표면 실제 결과](SEARCH-SURFACE-PARITY-2026-09-09.json).

검증 환경의 SB_CONFIG·XDG_DATA_HOME·state_root도 임시 경로로 고정했다. 웹 서버는 종료했다. MCP는 별도 프로세스 stdio 인수가 아니며, 실제 자비스 인증 세션·사용자 업무 공유까지 검증한 것은 아니다. 공용 레지스트리 과거 영향 정리와 전체 운영 인수는 남는다.
