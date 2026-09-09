# 복원 조회 응답 직후 정책 철회 경합 검증

기준 SB71a0a15, 자비스 격리 빌드195b1a7. 기존 실제 삭제 이력→복원→scoped client 시나리오를 확장했다. 제품 코드 변경은 없다.

실제 provider stdio transport가 data 응답과 KeepBeta 본문을 반환한 것을 확인한 직후, 자비스 client가 이를 소비하기 전에 격리 policy 파일에서 세션을 철회한다. readPage와 search 각각 이 경계를 통과시켰으며 둘 다 MEMORY_ACCESS_SCOPE_UNAVAILABLE로 reject됐다. 성공 응답을 가짜 오류로 바꾸거나 transport를 생략하지 않았다. 정상 응답 관측 횟수는2다.

각 철회 검사 뒤 정책을 복구하여 같은 client와 같은 동작의 정상1페이지 조회를 확인했다. 기존 다른 프로젝트 직접조회 거부/검색0, 요청 전 철회 거부, 삭제 기억0·남은 기억1, 자비스/provider highwater1·복원 blocked/scan0 조건도 함께 유지했다.

최종 실제 acceptance exit0, 증거 /var/tmp/sb-jarvis-restore-9BT8ab, [결과](RESTORE-POLICY-RACE-2026-09-10.json). Node 구문·diff 검사 통과. 제품 소스 변경이 없어 전체 suite는 반복하지 않았으며1690통과/2skip 기준을 유지한다.

이 결과는 실제 자비스 client가 철회 이후 완료 결과를 반환하지 않는다는 증거다. provider에서 자비스 프로세스로 이미 도착한 bytes의 메모리/캐시 완전 삭제를 증명하지 않는다. 테스트용 정책·세션·권한·자료이며 운영 인증과 native 모델/사용자 업무 인수는 아니다. 운영 DB·서비스·다른 리포 변경 및 push 없음. 운영·DR·실제 업무/에이전트 수명 및 M1–M14 전체 목표는 남는다.
