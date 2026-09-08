# scoped 쓰기 전제와 지원 기능 표시

2026-09-09. JARVIS 제품 `0825e0d`, SB 인수 `6831147`.

## 현재 코드 대조

`sb/mcp_remember_models.py`의 MemoryRememberRequestV3Model은 candidate_digest/classification_digest/receipt/본문을 받지만 승인된 owner/projects/policy_revision 분류를 구조화해서 받지 않는다. `sb/write_request_values.py`의 요청/영수증 키와 digest 검증도 현재 해당 범위 필드를 결합하지 않는다. JARVIS memory-candidate-material/types/reader의 classification에는 같은 의미의 프로젝트 접근 분류가 없다. `sb/pipeline.py`는 별도 config.source_access와 ledger.bind_source_access로 connector source를 분류한다. 따라서 요청의 classification_digest가 있다는 사실만으로 승인된 프로젝트 범위가 저장까지 전달된다고 볼 수 없다.

읽기 claim을 쓰기에 붙이거나, source/agent 문자열·본문 frontmatter를 프로젝트 권한으로 간주하는 구현은 보류한다. 기존 일반 owner 쓰기 경로를 없애는 결정은 아니다. scoped 쓰기 완성은 계속 전체 목표에 포함된다.

## 이번 구현

인증된 `GET /api/v1/memory/context/capabilities`를 추가했다. 기존 owner/cookie/CSRF 검사를 통과해야 하며 다음처럼 지원 범위와 설정 존재 여부만 반환한다.

```json
{"schema_version":1,"profile":"scoped-record-read-v2","configured":true,"supported_operations":["context"],"writes_supported":false,"authorization":"checked_per_request","readiness":"not_checked"}
```

configured는 server 옵션 존재 여부이며 정책 허용/키 유효/검색 준비 증거가 아니다. capabilities 조회는 provider나 DB를 호출하지 않는다. 미구성 server는 configured=false이며 문맥 조회는 기존처럼503이다. no-store 등 기존 HTTP 응답 보호를 재사용한다. 이 표면은 새 쓰기를 열거나 계약을 완화하지 않는다.

## 검증

- 관련 **45 passed / 3 files / 2.96초**, TypeScript 격리 emit·변경 파일 lint·JS 구문·양쪽 diff 검사 통과.
- HTTP 회귀: 미구성 capabilities 응답 확인, 쿠키 없는 호출401, backend proxy로 전달하지 않음.
- 실제 격리 HTTP/MCP 인수: 구성된 capabilities가 context만 지원하며 쓰기 false/readiness 미검사임을 확인했다. POST /api/v1/memory/remember는404, upstream capture에 쓰기 요청 없음.
- 실제 정상 records2, 다른 agent 공유2→프로젝트 제한0/원 agent2, 새 로그인 재사용, 정책403/입력400/만료401 및 기존 MCP 인수는 유지됐다.
- [결과 JSON](SCOPED-CAPABILITIES-2026-09-09.json), 원본 `/var/tmp/page-access-acceptance-qtm9_y1m/scoped-mcp-result.json`.

실제 Tailnet·운영 키/데이터를 사용한 검증은 아니며 fixture 신원·정책·원본·시계와 실제 HTTP/MCP를 사용했다. 이번 전체 Python/Vitest 검사는 재실행하지 않았다. 운영 서비스/DB/설정을 수정하거나 배포하지 않았다.

## scoped 쓰기를 완성할 구현 순서

1. **범위가 결합된 후보/분류 버전:** JARVIS의 검증된 작업/인증 문맥으로 owner·projects·policy revision을 공급하고 candidate/classification 및 승인/dispatch 증거에 결합한다. 기존 digest domain/저장된 bytes는 수정하지 않는다. 새 버전 번호는 양쪽 모든 요청·분류 타입을 대조해 확정한다.
2. **승인 범위가 결합된 쓰기 계약:** remember request/payload/receipt·idempotency identity에 같은 분류 digest와 provenance를 결합한다. 읽기 목적 fence/claim을 쓰기 권한으로 재사용하지 않는다. 기존 authority 경로를 확장하며 별도 권한 엔진을 만들지 않는다.
3. **수락→처리→봉인 계보:** provider가 수락 시 권한·본문·분류를 검증한 뒤 ledger의 해당 요청/원본에 불변 결합한다. 일반 connector 설정만으로 서로 다른 요청 프로젝트를 한 범위로 덮지 않는다. 재처리·정정·합성 page의 모든 입력 요구 범위로 전파한다.
4. **완료 영수증과 재조회:** accepted/pending을 저장 완료로 표시하지 않는다. 실제 처리 영수증의 요청 ID/본문·분류 identity를 검증하고 새 agent가 허용 범위에서만 회수한다. 불허 project, 중복 요청, 실패 실행·철회·복구 후 재유입을 함께 시험한다.
5. **활성화:** 양쪽 버전 계약/수명주기/실제 HTTP 또는 MCP 쓰기→영수증→다른 agent 재사용을 통과한 뒤에만 capabilities의 writes_supported를 바꾼다.

이 목록은 구현 완료 증거가 아니다. 이번에는 지원 기능 표시와 쓰기 거부를 구현·검증했으며 scoped 쓰기 계약·저장 계보 작업은 미완료다. 전체 목표를 축소하거나 완료 처리하지 않는다.
