# Provider와 원본 v3 요청을 결합한 scoped v4 데이터

2026-09-09. 이전 단계의 충돌 진단 수정과 커밋은 진전으로 확인했다. 이번에는 M2 범위 쓰기의 요청 데이터 codec을 양쪽에 구현했다. 전송 계약 공개·수락·배포 완료를 뜻하지 않는다.

## 구현

자비스 `prepareMemoryScopedWriteRequest`는 기존 policy/source/review 준비 검사를 통과한 뒤 private spool의 검증된 v3 요청을 포함하는 schema_version 4 데이터를 만든다. 수신 provider, source_request, preparation, 작성자 principal/agent/session, 유효 시각, idempotency key, request ID/digest를 결합한다.

쓰기 정책 resolver 결과에 provider_instance_id를 명시하고 요청의 수신 provider와 일치해야 한다. 다른 provider 문자열을 builder에 넣으면 거부한다. 중복 키는 provider와 기존 scoped identity digest를 domain `orca-jarvis/memory-scoped-write-idempotency/v4`로 결합한다. request digest는 전체 데이터를 별도 v4 domain으로 결합한다. 같은 입력은 같은 결과이며 다른 provider로 바꿔 보낼 수 없다. 기존 v1/v3 domain과 저장된 bytes를 수정하지 않는다.

세컨드브레인 `parse_scoped_write_request`는 필드/버전/크기/수신 provider, 기존 v3 parser, scope preparation parser, candidate/classification·제목·본문·민감도·보존 기간 일치, 작성자 식별자, 만료 상한과 전체 identity를 검증한다. 결과는 frozen 값과 canonical bytes로 보존한다. 해시 일치가 권한을 증명한다고 간주하지 않는다.

## 검증

- SB codec/preparation/materialization/walking skeleton: **33 passed / 3.81초**. 개별 v3 검증이 통과하도록 제목·본문·보존 기간과 v3 hash를 바꾸고 v4 hash도 다시 계산한 요청이 원래 preparation과 다르면 거부한다. 기존 v3 parser는 v4 wrapper를 거부한다.
- JARVIS 정책/scope review/기존 제품 구성: **13 passed / 7.33초**. TypeScript noEmit·격리 emit·변경 파일 ESLint, 전체 SB Ruff 및 diff 검사 통과.
- 실제 격리 v3 classify CLI→서명 검토→비공개 v3 정책 파일→v4 builder에서 동일 입력 재생성과 다른 provider 거부를 확인했다. `scoped-dispatch-preparation-acceptance.mjs <build> v3 --write-policy --write-request`로 재현한다.
- 생성한 v4를 독립 Python 프로세스로 검증한 뒤 기존 내부 materialization 인수에 연결했다. 원문51bytes, 새 세대 봉인·활성화, 독립 reader3개에서 records4/4 및 불허 프로젝트 거부. [실행 결과](SCOPED-WRITE-REQUEST-V4-2026-09-09.json). 테스트 벡터 `tests/fixtures/scoped_write_request_v4.json`은 합성 데이터다.

## 보류·남은 연결

v1 원본을 v3로 재명명하는 자동 변환은 보류했다. 새 builder는 정확히 v3 기억 원본만 받는다. 정책의 provider와 실제 전송 대상을 다르게 지정하거나 기존 hash 검사를 완화하는 방식도 채택하지 않았다.

현재 v4는 내부 codec이며 MCP contract JSON·request store의 지원 버전을 확대하지 않았다. RequestStore는 여전히 1/2/3만 수락하고 RequestExecutor는 이 v4를 실행하지 않는다. 공개 프로필은 모든 수락/처리/영수증 연결 후 확정해야 한다. 이를 우회하여 기존 v3 수락 함수에 scope를 별도 인자로 붙여 넣지 않는다.

다음 구현은 기존 검토 영수증 단일 소비와 outbox 삽입 transaction, provider 수락 원장의 v4/불변 분류 보존, RequestExecutor의 source_access 전달 및 완료 영수증 검증이다. 현재 codec만으로 서명·실제 정책·소비 여부를 확인할 수 없으므로 신뢰하지 않는 transport에서 바로 저장하지 않는다. 실제 MCP 저장→영수증→다른 agent 인증 세션 회수, 전체 M1~M14·운영·삭제·복구 인수는 계속 남는다. 이번 전체 Python/Vitest를 재실행하지 않았으며 이전 전체 SB 1,169통과/2skip와 구분한다.
