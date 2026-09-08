# 자동 승인 후보의 CLI 발행 연결

2026-09-09. JARVIS 제품 `aa825f0`.

## 문제와 변경

기존 CLI classify는 검증 결과를 approved 후보로 저장했지만 review spool 발행은 awaiting_confirmation에만 적용됐다. 따라서 검증 결과가 자동 승인된 경우 기존 dispatch 준비에 필요한 spool과 publication 원장이 없었다.

CLI 분류 직후 `publishAutomaticMemoryCandidate`를 호출한다. 이미 approved이고 required_confirmation=false인 remember 후보만 처리한다. 현재 원본 권한과 격리를 검사하고, 기존 후보의 생성 시각으로 분류를 재구성해 전체 내용이 저장된 분류와 같은지 확인한다. 기존 review/dispatch spool writer와 publication 테이블에 정확한 자료를 발행한다. manual confirmation·correct 후보의 경로는 유지한다.

자동 발행의 receipt 참조는 원래 owner 결정 receipt 또는 verification evidence다. verified outcome에 control command가 없으면 기존 dispatch envelope의 참조 필드에 verification ID와 source digest를 사용한다. 새 owner 서명이나 control 승인 명령을 만드는 것이 아니다. 이후 일반 write authority 검사는 기존 원본 권한 원장을 계속 사용한다.

발행은 immediate transaction에서 수행하고 파일 발행 후 시각·원본 권한·격리를 다시 검사한다. DB commit 전 파일만 남은 경우 재실행은 기존 후보 시각과 동일한 bytes를 재사용한다. publication conflict를 무시하고 성공 처리하지 않도록 원장의 두 spool digest를 다시 대조한다. 재실행은 새 후보·outbox·승인·provider 요청을 만들지 않는다.

## 검증

- 기존 CLI 수동 확인 경로 13개 통과. 신규 파일 문법 오류는 수정 후 재실행했다.
- 최종 자동 발행/범위 준비 7 passed / 7.33초. v1/v3 자동 발행, 반복 실행 DB 행 불변, 기존 일반 dispatch 준비와 원본 write authority 통과, 파일 발행 직후 주입한 실패의 DB rollback 및 다음 호출의 동일 bytes 재사용을 확인했다.
- TypeScript noEmit·격리 emit, 변경 파일 ESLint, JS 구문·diff 검사 통과. 테스트 mock의 this 타입 오류도 수정 후 재검사했다.
- v3 검증 fixture의 수동 review/dispatch 생성을 없애고 실제 CLI execute로 교체했다. 컴파일된 CLI→후보 DB→두 private spool→기존 요청 reader→signed scope review→scoped 준비를 실행해 한국어/CRLF 본문 일치와 원본 검증 철회 후 준비 거부를 확인했다.
- [실행 JSON](AUTO-CANDIDATE-PUBLICATION-2026-09-09.json): prior_request_schema=3, cli_published=true, scoped_write_completed=false. helper는 [scoped dispatch 인수](scripts/scoped-dispatch-preparation-acceptance.mjs)에 격리 build와 `v3` 인수를 주고 JARVIS cwd에서 실행한다.

fixture 키·정책·시계·합성 검증 결과와 실제 제품 CLI/API/DB/파일을 사용했다. 운영 서비스·모델·네트워크 provider 저장은 실행하지 않았다. 전체 스위트는 이번에 재실행하지 않았다.

## 한계와 후속 구현

파일 발행 실패 테스트는 결정적 예외 주입이며 실제 SIGKILL·다중 OS writer 인수가 아니다. 실패 후 남은 파일은 private root에 유지되고 같은 후보 재시도에서 채택한다. 재시도하지 않는 오래된 orphan의 정리·삭제 수명 인수는 추가로 필요하다. 원본 권한이 철회되면 재발행도 거부하며 강제로 분류를 재생성하지 않는다.

이번 완료 범위는 CLI 자동 발행 연결이다. 일반 library classify에 spool side effect를 일괄 추가하지 않았다. scoped request codec·승인 단일 소비/outbox 원자화·현재 프로젝트 정책·provider 원본 분류·완료 영수증·새 agent 재조회는 여전히 미완료다. 기존 provider 프로필과 writes_supported=false는 유지했다. 운영 DB/설정/서비스 변경 및 push는 하지 않았다.
