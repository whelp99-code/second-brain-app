# 근거 안내 실행물 인수 — 2026-09-09

JARVIS 61b8a42를 git archive로 별도 디렉터리에 풀어 TypeScript emit 및 migration 복사를 완료했다. 현재 운영 dist는 변경하지 않았다. 기존 잠금 의존성 후보와 lock SHA256 및 직접 runtime 의존성 7개 일치 검사를 통과한 뒤 해당 node_modules를 개발 후보에서 재사용했다. 이 확인은 전이 의존성/봉인 릴리스 전체 검사와 구분한다.

빌드: /var/tmp/jarvis-evidence-guidance-bhseao09/source/dist

실제 Node stdio MCP 실행물에 SDK 클라이언트로 연결하여 jarvis_memory_context 한 개가 노출되고, ‘결과 존재/순위는 질의에 답함을 보장하지 않는다’ 안내가 실제 목록에 포함됨을 확인했다. 이 목록 검사는 자격증명이나 기억 조회를 수행하지 않는다.

별도로 새 빌드의 실제 TLS/gateway/CLI/provider MCP 통합 4경로가 exit 0으로 통과했다. 정상 요청의 완료→새 로그인→독립2클라이언트 회수와 철회/만료 차단을 재검증했다. 전달 identity·원문·검증 작업·시각은 fixture다. native 모델이 안내를 실제로 준수하는지는 이번에 검증하지 않았다.

운영 전환/계정/DB 변경 없음. 새 실행물을 다음 native 품질 검증에 사용할 수 있다. 결과는 동명 JSON에 보존했다.
