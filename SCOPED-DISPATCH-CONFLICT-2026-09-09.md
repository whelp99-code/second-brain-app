# 기등록 후보의 scoped 준비 충돌 구분

2026-09-09. JARVIS `fc40358`. 이전 단계는 명시적 정책 검증과 16개 검사·두 리포 커밋으로 진전했다.

## 관측과 수정

이미 일반 outbox에 등록된 후보가 scoped 준비를 통과할 것이라는 최초 가정은 재현에서 확인되지 않았다. 기존 코드는 `MEMORY_CANDIDATE_INPUT_INVALID`로 거부했다. 따라서 우회 취약점을 수정했다고 보고하지 않는다. 이번 결함은 이미 제출된 후보와 잘못된 입력을 구분하지 못하는 오류 진단이다.

`prepareMemoryScopedWriteWithPolicy`는 저장된 범위 검토 command의 candidate ID로 기존 outbox 등록 여부를 확인하고 `MEMORY_SCOPED_WRITE_ALREADY_DISPATCHED`를 반환한다. 호출자가 넣은 검증되지 않은 candidate ID를 조회 키로 사용하지 않는다. 현재 정책 조회 이후, 원본 준비 전 및 마지막 정책 callback 이후에 검사한다. 기존 후보당 하나의 outbox 제약과 이전 요청 bytes를 변경하지 않는다.

## 검증

- 회귀 추가 시 1 failed/4 passed: 기대한 구체적 오류 대신 기존 입력 오류를 반환했다.
- 수정 후 scope review/access policy/outbox saga **21 passed / 11.61초**. TypeScript noEmit·격리 emit·변경 파일 ESLint 및 diff 검사 통과.
- 실제 격리 컴파일 API/SQLite/private spool/서명 검토→기존 control claim→outbox enqueue→scoped 재준비 경로를 실행했다. 등록 전 준비 가능, 등록 후 구체적 충돌 오류, 기존 outbox **queued**, scope review **approved**, 검토 소비 없음, 원장 행 수 불변, provider 호출 **0**을 확인했다.
- [실행 결과](SCOPED-DISPATCH-CONFLICT-2026-09-09.json), 재현 helper `scripts/scoped-dispatch-conflict-acceptance.mjs`. 합성 권한 resolver를 사용한 내부 API 인수이며 운영 인증/실제 모델/HTTP 저장의 증거는 아니다. 이전 단계의 실제 파일 정책 검증과 구분한다.

## 보류·후속

이미 등록된 후보를 다른 프로젝트 키로 다시 넣거나 기존 outbox UNIQUE 제약을 제거하는 방식은 채택하지 않았다. 이 검사만으로 scoped 쓰기가 완성된 것은 아니다. 향후 버전이 구분된 scoped 요청의 동일 요청 재조회는 검증된 기존 요청 identity를 통해 처리해야 하며, 새 쓰기 준비로 재해석하면 안 된다.

다음 완료 조건은 versioned request/receipt, 검토 단일 소비와 outbox 삽입 transaction, provider 수락 분류→봉인 계보, 실제 MCP 저장→완료 영수증→다른 agent 인증 세션 회수다. 전체 M1~M14 및 운영·삭제·복구 인수는 계속 남는다. SB Python 제품은 이번에 변경하지 않았고 전체 검사를 반복하지 않았다.
