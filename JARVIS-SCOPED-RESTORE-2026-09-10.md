# 복원 세대의 실제 자비스 프로젝트 제한 조회

기준 SB7061ba1, JARVIS 격리 빌드195b1a7 receipt 경로를 재사용했다. 앞선 실제 자비스 chain/effect proof→provider 복원→reference 조회 acceptance에 프로젝트 제한을 추가했다. 제품 코드 변경 없이 세 acceptance 스크립트를 추가/확장했다.

남길 합성 페이지는 fixture materialize_remember에 SourceAccess(principal:owner, project:a, policy:1)를 명시하여 출처·페이지 접근 분류와 함께 봉인한다. 백업 이후 별도 페이지를 실제 자비스 효과 경로로 삭제하여 양측 이력번호1로 만든다. 자비스 자체 authority에서 발급한 fence로 복원하고 후보를 격리 store에서만 활성화한다.

신규 restore-scoped-client.mjs는 같은 자비스 authority에서 createProductionMemoryAccessClaim, createFileMemoryAccessScopeResolver, createMemoryScopedClient 및 실제 stdio transport를 사용한다. scoped-record-read-v3에서 project:a의 페이지 조회/검색이 각각1페이지다. 정책 파일의 세션 project를 b로 바꾸면 직접 페이지 조회는 거부되고 검색 결과는0페이지다. 세션을 철회하면 MEMORY_ACCESS_SCOPE_UNAVAILABLE로 권한 발급이 거부된다. 모든 과정에서 자비스 삭제 chain을 초기화하거나 provider 번호를 복사하지 않는다.

최종 실제 실행exit0. /var/tmp/sb-jarvis-restore-b5dO6b, [구조화 결과](JARVIS-SCOPED-RESTORE-2026-09-10.json). 삭제0기록/유지1기록, 복원 highwater1, blocked_matches/scan_errors0, scoped 허용1/제한0/철회거부. 첫 실행에서 reference record에 없는 page_id를 사용한 harness 오류가 났다. 복원 후 합성 KeepBeta 페이지의 실제 ID를 probe 결과로 반환해 수정하고 전체 acceptance를 재실행했다.

재현: `TMPDIR=/var/tmp PYTHONPATH=. node scripts/jarvis-restore-acceptance.mjs /absolute/isolated-jarvis-build/dist`. Ruff sb/tests/Python probe, Node 두 스크립트 구문·diff 검사 통과. 제품 변경이 없어 전체 suite는 반복하지 않았으며 최신 제품 기준1690통과/2skip 유지.

신뢰 범위: 실제 자비스 발급/소비 코드와 provider stdio/삭제/복원을 사용하지만 session source·정책·권한 DB·자료는 합성 fixture다. 운영 인증 세션, HTTPS·native 모델, 사용자 업무의 완료 증거가 아니다. scoped v3만 이번 복원 시나리오에서 실행했으며 다른 프로필까지 확대하지 않는다. 실제 업무·운영 전환/복구·에이전트 수집과 삭제 수명·DR 및 전체 M1–M14는 미완료다. 운영 DB·서비스·다른 리포 변경과 push 없음.
