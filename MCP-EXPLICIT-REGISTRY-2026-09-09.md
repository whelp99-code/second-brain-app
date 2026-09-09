# MCP 검색의 명시적 레지스트리 전달

MCP의 기존 검색, 세대에 고정된 검색, desktop 검색 모두 SearchIndex 생성에서 Config의 knowledge_registry를 전달하지 않았다. reference 검색은 미분류 결과도 반환하므로 단순 결과 존재 검사로는 누락을 발견하지 못했다. 지정 레지스트리의 VERIFIED 상태를 확인하는 회귀로 수정 전 실패를 재현했다.

세 경로에 명시적 registry_path를 전달한다. 설정이 없으면 기존 fallback을 유지한다. 기존 프로필, 접근 범위, 세대와 fence 검사는 변경하지 않는다.

MCP·프로필 호환성·세대 관련 **20 passed, 5.55초**, Ruff/diff 통과. 실제 Claude로 앞서 생성한 임시 자료에 MCP Client를 연결해 검색2건의 VERIFIED 상태를 확인했다. 이 조회는 in-process MCP transport이며 native 모델을 재호출하거나 별도 프로세스 stdio를 검증한 것은 아니다. 환경의 다른 registry 경로는 생성되지 않았다. [조회 증거](MCP-EXPLICIT-REGISTRY-2026-09-09.json).

이번 직접 인수는 legacy 검색 경로다. 다른 두 경로는 코드 전달과 관련 호환성 검사를 확인한 범위다. 전체 운영 인수나 모든 에이전트 자동 수집 지원을 의미하지 않는다. 공용 레지스트리의 이전 검증 기록을 이번에 변경하지 않았다.
