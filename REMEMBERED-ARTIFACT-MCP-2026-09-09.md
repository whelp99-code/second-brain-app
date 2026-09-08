# 자비스의 수락된 기억 조회 연결과 v4 journal 읽기 수정

세컨드브레인 유지·네 OSS 장점 선별 흡수라는 인계 방향을 유지한다. 이번 변경은 공통 기억의 실제 저장→조회 경로를 연결하는 M2/M3/M7/M12 작업이다. 전체 M1–M14 완료를 뜻하지 않는다.

## 발견과 수정

자비스 `createMemoryScopedClient.readRememberedArtifact(request, acceptance)`를 구현했다. 과거 수락 시점으로 요청을 검증하고 비동기 전송 전에 복사한 뒤, candidate와 원문 해시로 정확한 페이지 ID를 계산한다. 실제 읽기 권한의 provider·owner·policy revision이 쓰기 요청과 같고 요청 프로젝트가 현재 허용 범위에 포함되어야 전송한다. 빈 프로젝트 범위는 wildcard로 해석하지 않는다. 기존 production issuer, 파일 정책 resolver, supervised stdio transport, scoped read v2 계약을 재사용하며 새 공개 도구나 권한 발급 체계를 추가하지 않았다.

반환된 레코드는 기존 schema4 검증기로 해시와 세대·삭제 fence를 확인하고, 인용 위치 순서로 다시 정렬해 원문의 문장 순서와 중복을 대조한다. 출처·민감도·SID도 일치해야 한다. Python 줄 분리/공백 제거와 사용자 footnote 이스케이프 규칙을 따른다. 민감도 때문에 본문 표시가 가려진 경우에도 원문 문장 해시로 대조하며 반환 결과에는 본문을 포함하지 않는다. 빈 결과, stale, 도구 오류, 원문/출처 변경은 성공으로 반환하지 않는다. 같은 기억을 읽을 때 세대 ID가 최초 쓰기 세대와 같아야 한다는 조건은 두지 않는다.

모의 transport 검사를 통과한 후 실제 MCP를 실행하자 첫 조회가 `REQUEST_SCHEMA_UNSUPPORTED`로 거절됐다. v4 쓰기 완료 후의 journal을 MCP의 기존 기본 RequestStore가 열지 못하는 실제 연결 결손이었다. 진단용 임시 trace는 원인 확인 후 제거했다.

RequestStore의 `maintenance_only`는 이미 존재하는 v4 schema를 인식하고 reader lease·삭제 high-water·기존 유지보수 경로가 동작하게 한다. v3를 v4로 업그레이드하지 않으며 새 요청 수락·취소 수락·실행 claim을 거절한다. 읽기 전용 SQLite 연결이라는 의미는 아니다. MCP에는 scoped 정책이 명시된 읽기 경로에만 적용했다. 기본 legacy 호출자의 v4 거절과 명시적 writer upgrade는 유지한다.

## 검증 근거

- JARVIS 최종 관련 53개 테스트 통과(9.62초). Python이 실제 생성한 4개 레코드 fixture 사용. 프로젝트/정책 전송 전 거절, 응답 중 철회, 비어 있는 결과, 해시를 다시 계산한 출처/본문/위치 변조, 세대 해시 불일치, 도구 오류, 비동기 요청 변조를 검사했다.
- TypeScript noEmit 및 격리 경로 emit 통과, 변경 파일 ESLint 통과. 첫 lint의 정규식/미사용 변수 오류는 수정했다. 이후 다중 프로젝트 권한의 정상 읽기를 추가 검증해 1건의 과잉 거절을 재현했고, 완전 일치에서 범위 포함 검사로 수정한 뒤 최종 53개를 통과했다. 운영 dist는 빌드하지 않았다.
- SB 관련 24개 테스트/7.41초 및 Ruff 통과. maintenance 모드에서 v3/v4 schema 불변, 기본 legacy v4 거절, 수락/claim 거절, FK 무결성을 검사했다.
- 최종 SB 전체 회귀: **1,237 통과/2 건너뜀, 215.74초**. `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py` 실행. 선택적 embeddings 테스트는 제외했다.
- [실제 프로세스 결과](REMEMBERED-ARTIFACT-MCP-2026-09-09.json): 내부 v4 acceptance/executor가 proved를 기록한 저장소를 자비스 production issuer·파일 정책·supervised transport로 조회했다. 실제 MCP 프로세스 재시작 뒤에도 같은 4개 record ID가 반환됐다. 여러 프로젝트 권한을 가진 reader도 대상 프로젝트가 포함되면 정상 조회했다. provider 파일 정책 개정과 issuer 세션 정책 철회는 각각 거절됐다. 실행 도구: `scripts/remembered-artifact-mcp-acceptance.py <isolated-JARVIS-build>` 및 consumer.mjs.

재현은 격리 DB/디렉터리, 고정 시계, 테스트 키와 테스트 세션을 사용한다. 초기 쓰기 권한 callback=True는 fixture다. 실제 제품 모듈과 프로세스를 통과했다는 증거이며, 운영 사용자의 인증·정책 또는 배포 인수 완료 증거는 아니다. 테스트용 시계/진단은 제품 코드에 넣지 않았다.

## 보류와 다음 완료 조건

결과 이름은 `remembered_content_observed`다. 공개 read v2 응답에는 정확한 저장 source/page 분류가 없어 SB 내부 artifact 검사와 같은 수준의 분류 일치를 증명하지 못한다. 또한 현재 content 관찰만으로 과거 proof의 진위나 특정 outbox 완료를 판정할 수 없다. 따라서 자동 settled/control completed는 보류한다.

다음 연결은 정확한 분류 증거를 담는 인증된 응답 계약, 현재 정책/삭제 fence 재검사와 durable proof 소비, 실제 v4 권한 검증기 및 공개 dispatch다. proof의 최초 결과 세대와 현재 읽은 세대를 구분하고, 삭제·교정·권한 철회 후 과거 결과를 재사용하지 않아야 한다. 새 MCP/worker 버전의 함께 배포 검증과 전체 에이전트·운영 인수는 남아 있다. 서비스 재시작·운영 데이터 수정·배포·push는 하지 않았다.
