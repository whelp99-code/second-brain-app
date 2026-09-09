# 정정 후 접근 분류와 저장 실패 복구 인수

기준 제품 d231ba2. 제품 코드 변경 없이 기존 실제 provider lifecycle의 정정 경로를 분류된 초기 기억으로 확장했다.

초기 fixture는 source_access=owner/project:a/policy:1과 정확한 본문 지식 상태를 materialize/봉인한다. 이후 실제 correct 접수·효과·proof를 처리한 결과 classified_page 및 require_scope가 같은 scope를 허용하고 다른 owner/project/policy를 각각 거부한다. 요구사항은 초기와 완전히 같다. fixture의 접근 분류는 시험용이며 JARVIS 인증 세션의 실제 claim 발급 인수로 해석하지 않는다.

lexical/hybrid 각각 미승인 정상, 승인 정상, 지식 상태 저장 실패, 접근 분류 저장 실패의 네 경우를 실행했다. 두 실패 경우 모두 reconciling 상태와 이전 활성 세대 유지, 새 executor의 lease 만료 후 proved 완료 및 tombstone 순번/루트 불변을 검사했다. 복구 뒤 접근 제한·단일 정정 문장·검색 승인 상태를 확인하고 export→forget→최종 proof/MCP 검증까지 기존 경로를 유지했다.

`TMPDIR=/var/tmp uv run pytest -q tests/integration/test_memory_lifecycle.py tests/test_effect_access.py --tb=short`: **15 passed / 37.97초**. 실제 lifecycle 조합 8개와 helper 7개다. Ruff 전체·diff 통과. 초기 13건 검사도 통과했으며 import 정렬 지적을 수정한 후 최종 확장 조합을 실행했다.

정상 복원 분류/지식 상태, 실제 JARVIS 세션 네트워크 회수, 취소 경쟁·다른 프로세스 강제 종료의 분류 인수, 최신 설치·실제 사용자 업무·운영 및 M1–M14는 남는다. 전체 suite는 이번 테스트 추가 후 다시 실행하지 않았다. 운영 DB·서비스·공용 registry 변경과 push 없음.
