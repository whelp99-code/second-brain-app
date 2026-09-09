# 접근 분류 재결합의 실제 강제 종료 인수

기준 제품 04ee493. 제품 코드 변경 없이 기존 spawn/SIGKILL 통합 테스트를 source_access가 있는 초기 기억으로 확장했다.

종료 지점은 지식 상태 저장 직전, 지식 상태 재결합 후 접근 분류 저장 전, 접근 분류 재결합 완료 후 publication 전, active 포인터 전환 직후의 네 곳이다. 자식의 Event 도달/생존을 확인한 뒤 소유 자식만 SIGKILL로 종료하고 exitcode를 확인한다.

새 처리기가 동일 삭제 요청을 proved로 복구하고 tombstone 순번/루트가 중복 증가하지 않음을 확인했다. 남은 기억은 active VERIFIED이고 classified_page의 requirements는 원래 SourceAccess와 완전히 같다. 동일 owner/project/policy는 require_scope를 통과하고, 세 요소 중 하나씩 다른 scope는 각각 거부된다. 포인터 전환 후 복구에서는 이미 공개된 effect를 다시 실행하지 않는 감시도 유지했다.

`TMPDIR=/var/tmp uv run pytest -q tests/integration/test_effect_knowledge_sigkill.py tests/test_effect_access.py --tb=short`: **11 passed / 10.54초**. 실제 SIGKILL 4경우와 helper 7경우다. Ruff 전체·diff 통과. 초기 상태는 시험용으로 materialize/분류/승인했으며 native 모델과 실제 JARVIS 인증 세션 인수가 아니다.

전원 손실·디스크 오류, 정정 취소 경쟁, 정상 복원 지식/접근 분류, 실제 JARVIS claim·사용자 업무·최신 설치와 운영 및 M1–M14는 남는다. 전체 suite는 이번 테스트 변경 후 다시 실행하지 않았다. 운영 DB·서비스·공용 registry 변경과 push 없음.
