# scoped 쓰기 범위 검토 계약

상태: 범위 검토 구현·격리 인수 완료, scoped dispatch 미완료. JARVIS 제품 `303f0d1`. 기존 scoped 쓰기 결손 보고서의 후보→승인 선행 단계를 구체화한다.

자비스의 기존 ControlPlane 요청·서명 영수증·철회 저장소를 재사용한다. 별도 승인 서버/키/원장/서명 형식을 추가하지 않는다. 새 비실행 action `memory.scope.review`는 현재 후보에 결합된 전체 범위 제안을 명시적으로 검토한다. 기존 `memory.confirm`·일반 remember 요청의 bytes와 의미는 유지한다.

제안 전체를 command args에 포함하고 candidate ID와 proposal digest를 target에 넣는다. 명령 digest가 승인 대상 범위를 포함한다. stage와 approve 시 현재 후보·만료·격리를 재검사한다. 검토 영수증을 읽는 함수도 현재 제안, 명령 digest, 서명, owner, decision key, 만료 및 철회를 확인한다. 다른 제안의 승인을 가져다 쓸 수 없다.

검토 승인은 provider 쓰기 권한이나 저장 완료 영수증이 아니다. API는 `writes_authorized=false`를 명시한다. 자동 승인하지 않고 기존 owner 서명 경로를 따른다. 기존 control 명령은 max_uses=1이며 후속 scoped dispatch가 동일 영수증의 원자적 소비와 버전 계약을 구현하기 전에는 쓰기를 개방하지 않는다. UI/CLI 연결·쓰기 요청·source 분류·완료 영수증·다른 agent 재조회는 후속 P0다.

## 구현

- `stageMemoryScopeReview`: 현재 제안으로 명령을 생성한다. 같은 제안을 재시도하면 같은 명령을 반환한다. 다른 프로젝트 제안은 별도 명령 digest를 가진다. 자체 서명·승인·provider 요청은 수행하지 않는다.
- `ControlPlane.stage/decide`: 새 action에 한해 현재 후보와 격리를 재검사한다. owner·level3·비실행 검토 계약을 유지하며 만료는 제안 만료를 넘지 않는다. 승인 시 재검사 실패는 영수증 저장과 상태 변경을 rollback한다. reject는 격리 상태에서도 가능하다.
- `readApprovedMemoryScopeReview`: 기존 결정 키의 서명과 현재 approved 상태, 명령 digest, 제안 전체, 만료, key/receipt/command 철회와 이미 소비된 명령을 검사한다. 서명된 검토를 조회할 뿐 영수증을 소비하지 않는다. 후보의 사실성·현재 프로젝트 정책 자체를 승인하는 API는 아니다.
- 기존 candidate v1, memory.confirm, 일반 remember/provider 계약과 migration bytes는 변경하지 않았다. 새 API를 기존 CLI/HTTP 메뉴에 노출하는 작업은 아직 하지 않았다.

## 검증

- 관련 candidate scope·scope review·ControlPlane **15 passed / 3 files / 13.04초**. action 계약 회귀 **3 passed / 0.656초**.
- TypeScript noEmit·격리 emit, 변경 파일 ESLint, JS 구문과 diff 검사 통과.
- 컴파일된 제품으로 fixture DB에 후보를 저장하고 기존 owner 결정 키로 실제 Ed25519 receipt를 서명·적용했다. **독립 Node 프로세스 6개**가 같은 DB를 새로 열어 제안 정상/변경/격리 및 서명 검토 정상/다른 프로젝트/철회를 검사했다.
- 승인된 제안의 검토는 수락하되 writes_authorized=false, 다른 프로젝트의 유효한 제안에 이전 승인을 적용하면 MEMORY_SCOPE_REVIEW_INVALID, 취소 후 같은 승인 재조회도 동일하게 거부했다. 검토 조회 전후 DB 행 불변, 승인 전후 memory_outbox 증가 없음.
- [실행 결과](SCOPED-WRITE-REVIEW-2026-09-09.json). 재현은 [candidate scope helper](scripts/candidate-scope-acceptance.mjs)를 JARVIS cwd에서 격리 build 경로와 함께 실행한다. 기존 제안 전용 결과는 이전 보고서에 보존했다.

fixture 키·고정 시각·합성 작업 근거를 사용한 실제 코드/API/프로세스/DB 검증이다. 운영 사용자 승인 화면·HTTP 저장·실제 모델 소비를 검증했다는 의미는 아니다. 전체 Python/Vitest는 이번에 재실행하지 않았다. 운영 서비스·설정·DB를 변경하거나 push하지 않았다.

## 유지하는 보류

서명 검토 결과를 기존 v3 remember에 억지로 붙이는 방식, 이 읽기 API의 반환을 쓰기 허가로 취급하는 방식은 보류한다. 다음 단계는 현재 작업 근거·정책 확인, 검토 영수증의 단일 소비, 양쪽 버전 요청/receipt/idempotency, 요청별 불변 분류를 함께 구현하는 것이다. capabilities의 writes_supported=false를 유지한다.
