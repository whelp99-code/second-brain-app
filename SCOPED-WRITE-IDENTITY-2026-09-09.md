# 범위가 결합된 쓰기 식별자

2026-09-09. JARVIS 제품 `0e6923b`.

## 계약

기존 일반 v1/v3의 idempotency identity에는 프로젝트 범위가 없다. 이를 수정하면 과거 요청의 식별자가 바뀌므로 별도 domain `orca-jarvis/memory-scoped-write-identity/v1\0`과 키 prefix `memidem:scoped:v1:`을 추가했다.

식별 재료는 schema_version=1, operation=remember, candidate ID/digest, classification digest, source digest, owner, 정렬된 projects, policy revision이다. 제안 digest와 승인 명령/영수증/digest/만료는 별도 결합 정보로 반환한다. 제안의 시각과 승인 receipt ID를 중복 방지 키에 넣지 않아 동일 후보·범위의 재승인이 중복 저장 키를 새로 만들지 않는다. 프로젝트나 정책 revision이 바뀌면 identity도 바뀐다. 후보당 중복 저장을 막는 기존 outbox 규칙은 후속 통합에서도 유지해야 한다.

자비스 `prepareMemoryScopedWriteIdentity`는 기존 signed review 검사와 후보 operation 확인을 같은 read transaction에서 수행한다. 기억 정정 후보를 remember로 바꾸지 않는다. 세컨드브레인 `scoped_write_identity`는 정확한 키·정수 버전·후보/digest 형식·owner·프로젝트 정렬/중복·policy revision을 검사하고 독립적으로 canonical bytes와 digest/key를 계산한다.

## 검증

- JARVIS 관련2통과/3.60초, TypeScript noEmit·격리 emit 및 변경 파일 ESLint 통과. 동일 범위의 다른 시각 제안을 새로 서명 승인해도 중복 방지 키가 같음을 확인했다.
- SB 9통과/0.14초, 변경 Python 파일 Ruff 통과. 범위 변경·키 순서 불변·잘못된 owner/operation·중복/역순 프로젝트·bool 버전·추가 필드를 검사했다.
- 실제 격리 DB의 owner 서명 승인에서 생성한 TypeScript 식별 재료를 Python 제품 함수로 다시 계산했다. identity digest와 idempotency key가 정확히 같고 다른 프로젝트는 다른 키였다.
- 기존 독립 프로세스7개 인수(일반 실행 거부·승인 보존·다른 범위/철회/격리 거부)도 재실행해 통과했다. [결과 JSON](SCOPED-WRITE-IDENTITY-2026-09-09.json).
- 재현: JARVIS cwd에서 [Node helper](scripts/candidate-scope-acceptance.mjs)를 격리 build 경로와 함께 실행해 JSON을 저장한 후, SB cwd에서 `uv run python scripts/scoped-write-identity-verify.py <결과.json>` 실행.

## 미완료 경계

이는 쓰기 계약의 식별 재료이며 완성된 v4 요청 codec이나 provider 수락 경로가 아니다. 반환은 writes_authorized=false이고 영수증을 소비하거나 inbox/outbox를 생성하지 않는다. Python 함수는 서명·권한 검증기가 아니며 digest 일치만으로 저장을 허용해서는 안 된다.

후속 P0는 동일 identity와 proposal/approval binding을 요청·영수증에 결합하고, 승인 단일 소비와 outbox 삽입을 원자화한 뒤 provider에서 요청별 source 분류를 보존하는 것이다. 현재 일반 MCP 계약/운영 서비스/DB/설정과 writes_supported=false는 유지했다. 실제 모델/운영 로그인/HTTP 저장·완료 영수증·다른 agent 회수와 전체 테스트는 이번에 검증하지 않았다.
