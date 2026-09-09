# 실제 OMO CLI 기억 도구 등록 — 2026-09-09

설치된 omo-ai 5.0.0-0.beta.46의 실제 CLI를 별도 임시 agent 설정으로 실행했다. 기존 balance router의 provider probe를 피하기 위해 설치된 bin/omo.js를 Node로 직접 실행했다. 이는 router를 포함한 전체 사용자 시작 경로의 검증은 아니다.

`--mode rpc --no-session`으로 시작해 get_loaded_surfaces 요청 하나만 보냈다. 모델 prompt/도구 실행 요청은 보내지 않았다. agent 설정에는 새 자비스 후보의 phone-memory-client MCP 서버와 유효한 형식의 가짜 세션 자격증명만 담았다. 실제 운영 계정이나 서버는 사용하지 않았다.

초기 실험에서 stdin을 곧바로 닫으면 종료 중인 서버 상태가 disabled로 관측됐다. 응답을 받을 때까지 stdin을 유지하도록 검사 도구를 수정했다. 이어서 확장 탐색을 꺼도 OMO 자체 플러그인이 _ast_grep MCP를 등록하는 것을 확인했다. 임시 mcp.json에 _ast_grep enabled=false를 명시한 뒤 최종 검사를 재실행했다.

최종 결과: exit 0, jarvis_memory connected/toolCount=1, _ast_grep disabled/toolCount=0. 연결된 MCP는 jarvis_memory 하나뿐이었다. 전역 사용자 설정은 변경하지 않았다. `authStatus=unsupported`는 stdio MCP의 OAuth 지원 상태이며, JARVIS HTTPS 인증 성공을 뜻하지 않는다.

`deploy/check-omo-memory-startup.py OMO_ENTRY JARVIS_ENTRY --node NODE`로 재현한다. 임시 설정/자격증명은 종료 후 삭제한다. RPC 출력 크기·대기 시간을 제한하고 실패 시 CLI 종료를 시도한다. 이는 전체 자식 프로세스·native 세션의 완전한 삭제를 증명하지 않는다. Ruff 검사와 실제 CLI 재실행 통과.

이번 증거는 실제 CLI의 MCP 초기화/등록까지다. 모델이 기억 도구를 선택하고 내용을 사용했는지, 자동 수집·주입되는지, 모든 built-in 도구가 비활성화됐는지는 아직 입증하지 않았다. 이전 OMO 엔진 호출 검증과 합쳐도 실제 모델 A→B 인수나 운영 완료를 선언하지 않는다.
