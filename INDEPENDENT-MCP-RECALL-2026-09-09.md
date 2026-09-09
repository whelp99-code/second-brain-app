# 별도 MCP 서버 프로세스 재시작 후 기억 회수

실제 Claude로 생성한 임시 wiki를 대상으로 MCP Client의 StdioServerParameters로 Python 자식 서버를 실행했다. 첫 서버를 종료한 뒤 두 번째 서버를 새로 시작해 검색과 본문 조회를 반복했다. HTTP나 MCP 응답을 mock하지 않았다.

각 회수 결과는 검색2건, 대상 wiki VERIFIED, 입력 사실 “금요일 오후 세 시” 및 web-inbox 출처 포함이었다. 두 서버의 page_id와 본문 SHA-256이 같았다. 환경의 다른 registry 경로는 생성되지 않았다. 모델은 다시 호출하지 않았다. [실행 증거](INDEPENDENT-MCP-RECALL-2026-09-09.json).

실행 경계: 최초 python -m sb.mcp 시도는 일반 임시 vault가 관리형 세대 경로 규칙과 맞지 않아 GENERATION_ACTIVE_PATH_INVALID로 거부됐다. 검사를 완화하지 않았다. 최종 검증은 자식 Python에서 build_server(Path(config.vault_root), config=config)를 명시적으로 생성하는 기존 일반 vault 경로를 사용했다. 따라서 기본 관리형 진입점 인수나 자비스의 인증 세션 연동 완료로 보고하지 않는다.

SB_CONFIG·XDG_DATA_HOME·state_root·knowledge_registry는 임시 경로로 고정했다. 두 자식 서버와 클라이언트는 종료했다. 스크립트는 /var/tmp/sb-independent-recall.py. 제품 코드는 변경하지 않았으며 공용 레지스트리의 과거 영향 정리는 남는다.
