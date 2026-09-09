# 복원 원장 저장 직후 오류와 재시도 검증

기준 제품 b834c3f. 검증된 전체 백업 복원에서 Ledger.bind_knowledge, bind_source_classification, bind_page_access 각각의 실제 저장 호출이 끝난 직후 ValueError를 주입했다. 세 지점은 정상 경로와 함께 parameterized integration test로 유지한다.

실패한 복원에서 기존 active generation ID 및 ledger.db bytes 해시 불변, tombstone high water 불변, generation staging 비어 있음을 확인했다. 실패 주입이 정확히 한 번 발생한 것도 검사한다. 패치를 제거하고 같은 RestoreRequest를 실제 sanitizer에 재시도하여, 삭제 내용 검색 불가·살아남은 승인 기억 VERIFIED·범위별 접근 제한을 확인했다. 이어 격리 fixture에서 복원 후보를 활성화하고 서명된 MCP 정상 조회 및 다른 범위/만료/키 철회 거부까지 검사했다.

이는 예외 경로의 정리와 동일 요청 재시도 증거다. OS SIGKILL·전원 손실, 다른 프로세스에서의 복원 재개, 운영 journal 소실 DR, 실제 JARVIS 권한 발급과 native 업무 인수의 증거로 사용하지 않는다. 기존 효과 적용의 SIGKILL 검증을 복원에도 적용했다고 주장하지 않는다.

`TMPDIR=/var/tmp uv run pytest -q tests/integration/test_memory_restore_reingress.py --tb=short`: **6 passed / 15.68초**. Ruff 전체 및 diff 검사 통과. 새 결함은 발견되지 않았으며 제품 코드 변경 없음. 전체 suite는 이전 5838b77의 1,674통과/2skip 기준을 유지하며 이번 추가 테스트 이후 재실행하지 않았다.

운영 DB·서비스·공용 registry·다른 리포 변경과 push 없음. 테스트에서만 복원 후보를 명시적으로 활성화한다. 실제 사용자 업무와 JARVIS/다중 에이전트 운영, 복원 강제 종료/DR 및 통합 M1–M14 목표는 계속 미완료다.
