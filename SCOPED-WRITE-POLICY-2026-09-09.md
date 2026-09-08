# 명시적 쓰기 정책과 현재 원본 권한을 scoped 준비에 연결

2026-09-09. JARVIS 제품 `9ab8293`. 이전 goal 단계 `732eaa1`은 분류 저장·봉인·실행 검증 및 커밋으로 진전했다. 이번에는 M2의 현재 쓰기 정책 결손을 구현했다.

## 변경

기존 `memory-access-policy.ts`의 비공개 파일·소유자·링크·읽기 중 파일 변경·정확한 필드·세션 만료 검사를 공유한다. 별도 정책 서버나 권한 엔진을 만들지 않았다.

- 기존 정책 v1/v2는 계속 읽기 전용이다. 새로운 정책 v3는 v2의 agent 행 구조를 유지하되 `methods`에 명시적 `sb_write_request`를 허용한다. 쓰기 resolver는 v3와 해당 메서드가 모두 있어야 범위를 반환한다. 같은 projects 목록이 행에 명시된 읽기/쓰기 메서드에 적용되므로 별도 쓰기 범위를 지원하는 버전은 아니다.
- 읽기 resolver는 메서드가 read/search/status인 경우만 평가한다. v3에 쓰기가 선언돼도 읽기 claim 생성에 쓰기 메서드를 전달할 수 없다. v3 행의 read 메서드도 여전히 명시되어야 한다.
- `createFileMemoryWriteScopeResolver`는 인증된 서버 session에서 agent/session을 받는다. 요청 body의 신원/프로젝트를 해석하지 않고 현재 파일을 매번 읽는다. 결과의 프로젝트 목록은 동결한다.
- `prepareMemoryScopedWriteWithPolicy`는 범위 검토·원본 write authority·private spool 본문 검사를 재사용한다. 현재 owner, 프로젝트 포함 관계, policy revision, 만료를 확인하고 두 번째 정책 조회와 비교한다. 마지막 정책 callback 뒤 원본 검증/철회 상태를 다시 검사한다. 개인 범위(빈 projects)를 프로젝트 권한의 wildcard로 인정하지 않는다.
- 반환 유효 기한은 session/policy와 범위 검토 중 더 이른 값이다. 반환의 `writes_authorized`는 여전히 false다. 승인 소비나 outbox 쓰기를 실행하지 않는다. 추후 enqueue transaction에서도 현재 정책/권한을 재검증해야 한다.

## 검증

- 정책·scoped review 관련 **11 passed / 5.79초**. 기존 v1/v2, 명시되지 않은 쓰기, 다른 프로젝트/revision, 정책 조회 중 철회, 마지막 조회 중 원본 증거 철회를 거부한다.
- 기존 read claim·제품 구성 회귀 **5 passed / 6.07초**. 합계 **16 passed**.
- TypeScript noEmit, 격리 emit, 변경 파일 ESLint max-warnings=0, diff 검사 통과.
- 실제 격리 v3 classify CLI→spool→서명 검토→파일 정책→준비 API에서 v3 수락·v2/다른 프로젝트/철회 agent 거부·read resolver의 쓰기 거부·원장 행 수 불변을 확인했다. [결과 JSON](SCOPED-WRITE-POLICY-2026-09-09.json). helper `scripts/scoped-dispatch-preparation-acceptance.mjs`의 `--write-policy`로 재현한다.
- 합성 인증 세션/정책/원본이며 실제 운영 키·서비스·모델 세션 인수는 아니다. SB Python 제품 소스는 이번에 바뀌지 않았고 이전 전체 결과 1,169 passed/2 skipped를 재실행한 것으로 보고하지 않는다.

## 보류와 다음 완료 조건

읽기 권한을 쓰기 권한으로 재사용하거나 v1/v2 정책에서 쓰기를 자동 허용하는 방식은 채택하지 않았다. 운영 정책을 v3로 자동 갱신하지 않았다. 명시적 쓰기 메서드는 현재 준비 검증용이며 HTTP/MCP 쓰기 capability를 활성화하지 않았다.

다음 작업은 버전이 구분된 요청/영수증, 검토의 단일 소비와 outbox 삽입의 원자성, provider 수락 원장에 불변 범위 결합이다. 이후 앞 단계의 materialize source_access 인자에 실제 수락 분류를 전달하여 MCP 저장→완료 영수증→다른 agent의 인증된 새 세션 회수를 검증해야 한다. 현재 준비값만으로 실제 저장 완료를 판단하지 않는다. 전체 M1~M14와 운영·삭제·복구 인수는 목표에 유지한다.
