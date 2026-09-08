# 기존 dispatch spool과 scoped 준비 연결

2026-09-09. `prepareMemoryScopedWriteFromDispatch`가 기존 `resolveSpooledDispatch`와 `hasSecondBrainWriteAuthority`를 재사용하도록 구현했다. 범위 검토가 승인됐다는 사실로 과거 작업 검증의 현재 유효성을 대신하지 않는다.

현재 signed scope review에서 후보 ID를 결정하고 private review/dispatch spool의 digest와 본문을 기존 reader로 복구한다. 같은 read transaction에서 원래 remember 권한을 확인한 뒤 후보 제목/본문 digest와 범위 identity를 결합한다. 호출자가 임의 본문을 전달할 필요가 없다. 권한 철회/만료/후보 상태 검사는 기존 일반 write authority 구현을 재사용하며 별도 권한 엔진을 만들지 않는다.

## 검증

- 관련 JARVIS 3 passed / 4.23초. 정상 spool 본문 일치, DB 행 불변, 원본 verification 철회 후 준비 거부 및 범위 검토 자체는 유효함을 확인했다.
- TypeScript noEmit·격리 emit·변경 파일 ESLint, JS 구문·diff 검사 통과.
- 컴파일된 제품 API와 실제 private spool/fixture DB/Ed25519 scope review를 사용한 재실행에서 정상 본문 복구, 원본 verification 철회 후 MEMORY_SCOPED_SOURCE_AUTHORITY_INVALID, provider write 호출0, 준비 전후 DB 행 불변을 확인했다.
- [결과 JSON](SCOPED-DISPATCH-PREPARATION-2026-09-09.json), [재현 helper](scripts/scoped-dispatch-preparation-acceptance.mjs). JARVIS cwd에서 `TMPDIR=/var/tmp node <helper 절대경로> <격리 build 경로>`로 실행한다.

실제 spool 인수의 기존 요청 버전은 v1이다. v3/owner-confirmed 모든 조합을 이번 인수로 검증했다고 주장하지 않는다. fixture 키·고정 시각·합성 작업 근거이며 실제 운영/모델/HTTP 쓰기 인수는 아니다. 전체 Vitest/Python은 이번에 실행하지 않았다.

## 미완료 및 보류

이 함수도 준비 결과만 반환하며 writes_authorized=false다. 원본 권한이 준비 시 유효해도 enqueue/dispatch 시 다시 확인해야 한다. 현재 프로젝트 정책 검사, 승인 영수증 단일 소비와 outbox 삽입, 양쪽 요청 codec, 요청별 source 분류·완료 영수증·다른 agent 새 세션 재조회는 여전히 미완료다. 준비 성공을 저장 완료 또는 쓰기 허가로 간주하는 방식은 보류한다. 운영 서비스/DB/설정은 변경하지 않았다.

## v3 후속 검증

schema_version2/plain-text-v1 후보를 실제 DB에서 분류하고 schema2 review와 schema3 dispatch를 기존 spool writer로 발행하는 fixture를 추가했다. 한국어·CRLF/LF 혼합·반복 문장·사용자 각주 형태가 포함된 본문을 복구해 정확한 UTF-8 바이트 일치를 확인했다. CRLF를 LF로 바꾸면 후보 content digest와 달라져 거부한다.

관련4통과/5.17초, 타입/noEmit·격리 emit·변경 테스트 lint·JS 구문/diff 검사 통과. 제품 코드는 추가 수정하지 않았다. 실제 컴파일된 코드와 v3 spool/DB/서명 검토 재실행에서 본문 일치와 원본 검증 철회 후 준비 거부, DB 행 불변을 확인했다. [v3 결과](SCOPED-DISPATCH-V3-2026-09-09.json). helper의 세 번째 인수로 `v3`를 지정한다. provider writer를 호출하는 경로가 아니므로 v3 결과의 provider_write_calls는 null(미계측)이며, 저장 완료는 false다.

fixture가 review/dispatch를 발행했다는 점을 구분한다. 현재 `MemoryCandidateStore.persist`의 attachReviewSpool 발행 조건은 awaiting_confirmation이며 `createMemoryCandidateReviewEnvelope`도 같은 상태를 요구한다. CLI classify는 store에 review root를 연결한다. 따라서 auto-approved verified 후보의 생성→spool 자동 발행까지 이번 시험으로 입증할 수 없다. 이 조건의 생산 경로 연결은 후속 확인·구현 대상으로 남긴다. owner-confirmed 전체 조합, 실제 CLI 자동 발행/저장, scoped 영수증 소비 및 provider 수락은 여전히 미완료다.
