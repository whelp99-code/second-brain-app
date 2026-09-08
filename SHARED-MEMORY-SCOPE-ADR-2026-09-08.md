# 공통 기억의 접근 범위 확장 — 구현 전 경계 결정

상태: **기존 코드 대조와 구현 방향 기록. 범위 기능 구현/활성화 완료가 아니다.** 일반 필터를 권한으로 승격하는 구현은 보류한다. 이번 실제 Codex/Claude 인수는 같은 소유자의 기억 공유만 검증했다.

## 현재 코드에서 확인한 결손

| 경계 | 현재 사실 | 필요한 변경 |
|---|---|---|
| 신원 | `MemoryReadFenceV1.principal_id`와 기존 receipt는 `principal:owner`로 고정 | 자비스가 확인한 사용자/agent 실행 문맥과 허용 project 집합을 버전 있는 외부 claim으로 전달 |
| 요청 | 현재 remember 후보/요청과 record 계약에는 권한으로 검증된 project 분류가 없음 | 출처 표지와 권한 분류를 구분하고 승인/요청 digest에 분류를 결합 |
| 원본·페이지 | record의 source/citation/content identity는 있으나 project/user 접근 분류가 없음 | 원본 분류를 파생 record까지 추적하고 봉인 세대에 결합. LLM 본문/제목/path에서 권한을 추측하지 않음 |
| 조회 | `SearchIndex.scope`는 active/candidate/reference라는 지식 상태 | 지식 상태 필터를 접근 범위로 재사용하지 않음. 별도 공통 판정 필요 |
| 조회 fence | 현재 fence는 provider, 목적, 시각, 삭제 high-water를 결합 | 새 범위 claim도 같은 신뢰 경계를 통과하고 요청 목적·대상·정책 버전에 결합 |
| 기존 클라이언트 | 삭제 sequence 0에서는 fence 없이 읽을 수 있음. 이후 기존 검증은 JARVIS 서명을 요구 | 기존 프로필을 조용히 확대하지 않음. scoped 프로필과 일반 owner 프로필을 명시적으로 구분 |
| 실제 실행 환경 | 같은 OS 사용자로 vault 파일에 직접 접근할 수 있는 client가 존재 가능 | MCP 응답 제한과 OS 파일 접근 격리는 서로 다른 인수 조건. MCP만으로 다중 사용자 보안 격리를 주장하지 않음 |

근거: `sb/delegations.py`, `sb/write_request_values.py`, `sb/remember_contracts.py`, `sb/memory_records.py`, `sb/mcp.py`, `sb/search.py`, 자비스 `src/memory-read-fence*.ts`와 `src/memory-candidate-*.ts`의 현재 계약. 기존 source agent 표지는 실행 권한이 아니다.

## 유지할 책임

- 자비스: 소유자/사용자와 작업 프로젝트, agent 실행 문맥, 접근 허용·철회 결정, 기존 서명 key lifecycle을 담당한다.
- Second Brain: 자비스가 발급한 범위와 원본 분류의 결합을 검증하고 같은 정책을 읽기/정정/내보내기에 적용한다. 새 권한 발급자·승인 UI·서명 엔진을 만들지 않는다.
- dev-wiki: 개발 결정·리포 관계 정본을 유지한다. 개인·업무 기억의 분류 근거와 개발 결정의 원문 정본을 혼동하지 않는다.
- 연결부: 전달받은 제한을 유지한다. 클라이언트 문자열 `agent_id`나 `project_id` 자체를 권한으로 사용하지 않는다.

## 구현할 계약과 순서

1. **원본 분류와 조회 claim을 같이 정의한다.** 자비스 candidate/classification과 remember 요청의 새 버전에서 owner/project 분류를 결합한다. 기존 V1/V2/V3 bytes와 digest를 바꾸지 않는다. 과거 무분류 기억은 owner 자료로 남기며 일반 project 공개 자료로 추정하지 않는다.
2. **소비 가능한 범위 claim을 전달한다.** 자비스 측 기존 서명/검증·폐기 경로를 재사용하되 새 domain/version, 만료, provider, 목적, policy revision을 명시한다. 같은 owner의 여러 agent 간 공유와 서로 다른 사용자의 격리를 별개 조건으로 검증한다.
3. **원본→record→페이지의 분류를 결합한다.** 여러 원본이 섞인 결과는 필요한 분류 전부에 접근이 허용되는지 검사한다. 허용되지 않은 원본이 들어간 page body나 citation을 부분 record 허용만으로 통째로 내보내지 않는다. 정책 변경 시 이전 projection/cache가 계속 사용되지 않게 한다.
4. **모든 표면에 같은 검사를 적용한다.** 검색·직접 page·recent changes·conflicts·target resolve·request status·export 및 다운로드를 포함한다. 쓰기 또한 허용된 출처/분류 범위에 결합되기 전 scoped client에 임의 capture를 열지 않는다. status의 원문 없는 정보도 타인의 요청 존재/상태를 누설하지 않도록 대조한다.
5. **정정·삭제·복원 수명을 연결한다.** 정정이 분류를 조용히 넓히지 않도록 하고, 새 범위 승인 없이 source classification을 바꾸지 않는다. 삭제·복원·재색인·export 만료/철회에서 제한이 되살아나지 않음을 검증한다.
6. **context pack에 같은 범위를 적용한다.** 선택·세션 중복 키·전달 receipt와 재공급은 사용자/agent 세션·project/policy revision·세대/삭제 상태에 결합한다. 범위가 다른 세션의 전달 이력을 공유해 기억을 누설하거나 정당한 전달을 생략하지 않는다.

새 MCP profile/schema 번호는 기존 계약을 대조하고 양쪽 구현 시작 시 확정한다. 현재 schema5에 범위 파라미터만 추가하거나 기존 fence1을 범위 claim처럼 해석하는 방식은 채택하지 않는다.

## 인수 조건

- 프로젝트 X의 기억을 X 허용 client가 원문·출처·버전으로 회수하고 Y 전용 client는 검색/직접 page/target/변경 목록/export/status 어디에서도 회수하지 못한다.
- caller의 project/agent 문자열 변경, 원문 frontmatter 변경, 오래된/철회된 claim, 다른 provider/목적의 claim이 권한을 확대하지 않는다.
- 다중 원본 record/page, 정정 후 분류, 삭제 후 재시도, 복원 후 재조회, export 및 context 캐시를 검사한다.
- 실제 Codex/Claude/JARVIS 연결부 각각에서 읽기·기록·수집·주입 능력을 따로 측정한다. CLI SDK 호환만으로 자동 문맥 공급까지 인정하지 않는다.
- 운영 다중 사용자 격리는 vault 파일 접근·서비스 계정/배포 경계도 별도 검증한다. 현재 단일 소유자 운영과 동일한 OS 권한을 다중 사용자 보안 경계로 취급하지 않는다.

이 ADR은 새 보류 사유를 만들어 전체 개발을 중단하는 문서가 아니다. 기존 unit 예산·수명주기·실제 앱 인수는 재사용하며, 다음 범위 구현이 기존 권한 엔진과 데이터 수명을 함께 확장하도록 기준을 남긴다.

## 2026-09-09 원본 분류 저장 첫 구현

`62b1609`는 신뢰된 로컬 수집 설정의 owner/projects/policy_revision을 source ID·URI·내용 해시에 결합해 원장v3에 보존한다. 이는 운영자 원본 분류이며 자비스가 검증한 작업/사용자 접근 claim의 대체가 아니다. 원문 frontmatter에서 분류를 추측하지 않고 과거 미분류 원본을 자동 공유하지 않는다. 같은 원본의 재분류는 별도 수명주기 연결 전까지 거부한다.

[전체 검사·실제 CLI·WAL 백업 수정 및 한계](SOURCE-ACCESS-CLASSIFICATION-2026-09-09.md). 다음은 원본 분류를 전체 파생 record/page와 결합하는 단계다. scoped MCP 프로필·자비스 요청/claim·정정/삭제/복원/context의 전체 조건은 아직 미완료이며 기존 owner 조회 범위는 바꾸지 않았다.

## 2026-09-09 파생 페이지 분류 보존

**2026-09-09 페이지 출처 보강 `f16c142`: [원본·이전 본문 요구 분류와 커밋 해시 결합](PAGE-ACCESS-PROVENANCE-2026-09-09.md).**
원장v4에 실제 컴파일 입력과 이전 페이지의 요구 원본을 보존한다. 인용 중복 제거·미추적 캐시·미분류 본문으로 접근 범위가 조용히 넓어지지 않도록 불완전 상태를 명시한다. 실제 격리 CLI 갱신·재실행에서 요구 원본1→2 및 커밋 해시 결합을 확인했다. 최종 전체1,108통과/2skip/210.84초·Ruff/diff통과·정적0오류/기존경고1. fake LLM 인수이며 scoped MCP 권한 검사와 전체 운영 인수는 남는다.


인계 방향과 기존 구현을 유지한다. 이 단계는 일반 컴파일 wiki의 provenance 저장이며 verified claim·record 및 모든 읽기/쓰기/복원/context 표면 검사를 완료한 것이 아니다. 정정/삭제/복원에서 분류를 결합하고 최신 정책을 다시 검증하는 다음 단계가 필요하다.

## 2026-09-09 봉인 record 조회와 내부 범위 판정

접근 판정은 같은 봉인 세대의 페이지 요구 분류 전체를 기준으로 한다. 모든 입력의 owner와 policy revision이 일치하고 요구 project 집합 전체가 허용 집합에 포함되어야 한다. 빈 project 집합은 wildcard가 아니다. 원본과 범위 양쪽이 빈 집합이면 같은 소유자의 개인 범위로 대조하며, project 범위를 가진 소비자에게 개인 원본을 자동으로 포함시키지 않는다. 개인 원본과 프로젝트 원본이 혼합된 페이지는 이 첫 범위 모델로 허용하지 않고 명시적인 개인 접근 능력의 계약이 마련될 때 확장한다.

봉인 원장과 Git 본문을 읽기 전용으로 대조하고, 미분류·변경된 원장·다른 세대는 거부한다. 기존 record wire와 MCP profile은 바꾸지 않는다. 이 내부 함수는 caller 인증을 하지 않으므로 외부 파라미터를 직접 연결하는 방식은 보류한다. 다음 단계는 자비스가 검증한 범위 claim을 연결하고 동일 검사를 전체 표면에 적용하는 것이다.


**2026-09-09 봉인 record 분류·내부 범위 판정 `62da782`: [구현·실제 CLI·남은 인증 경계](MEMORY-ACCESS-READER-2026-09-09.md).**
같은 세대 원장·커밋 본문·전체 원본 분류를 결합해 record를 읽고, 이미 인증된 scope의 owner/project/revision을 대조한다. 최종 관련32통과/8.42초·Ruff/diff·정적0오류/0경고. 실제 CLI 산출물의 요구 원본2/record2 및 네 범위 거부·읽기 불변을 인수했다. 내부 함수이며 caller 인증·scoped MCP·모든 표면 적용과 전체 운영 목표는 남는다.

## 2026-09-09 범위 claim 검증 계약

기존 읽기 fence v1을 범위로 재해석하지 않는다. 별도 `orca-jarvis/memory-access-claim/v1` 서명 domain의 claim을 추가하며 provider·principal·agent/session·project 집합·policy revision·정확한 요청 digest·fence digest·유효 시간을 결합한다. 검증은 기존 Ed25519 검증과 현재 공개키 집합을 재사용한다. 현재 fence v1의 principal:owner 제한을 그대로 대조하므로 첫 계약은 같은 소유자의 여러 에이전트/프로젝트 범위다. 다중 사용자 확대는 fence 계약도 함께 버전 변경하기 전까지 보류한다. 이 계약만으로 MCP를 공개하지 않으며 issuer는 검증된 작업/사용자 문맥에서만 발급해야 한다.


**2026-09-09 범위 claim 검증 `d220902`: [계약·실제 Node 서명/Python 검증·잔여 issuer 경계](ACCESS-CLAIM-VERIFICATION-2026-09-09.md).**
별도 서명 claim을 현재 읽기 fence·provider/principal·agent/session·정책·실제 요청·유효 시간에 결합한다. 페이지 provider/삭제 high-water도 대조한다. 최종 관련43통과/7.33초·Ruff/diff·정적0오류/0경고. 실제 Node 테스트 서명과 봉인 CLI 페이지 범위 판정을 인수했다. 운영 JARVIS 발급·scoped MCP·다중 사용자·전체 표면과 기존 운영 목표는 남는다.


**2026-09-09 JARVIS issuer `c5ad24b` / SB `3b2a08d`: [현재 키·범위 검사 발급과 실제 상호 검증](ACCESS-CLAIM-ISSUER-2026-09-09.md).**
매 요청 범위를 다시 조회하고 현재 DB 키 검사·fence·요청 digest와 만료를 결합한다. 기존 긴 provider/key ID 호환을 수정했다. JARVIS17통과/13.10초·SB31통과/6.02초·타입/lint/격리emit통과. 실제 issuer→Python→봉인 페이지를 인수했으나 scope resolver는 fixture다. 운영 resolver·scoped MCP 및 전체 운영 목표는 남는다.

## 2026-09-09 제한된 MCP record 조회 연결

명시적인 서버 설정 `mcp_scoped_read`가 있는 연결에는 `scoped-record-read-v1` 프로필을 적용한다. 첫 단계는 `sb_read_page`의 분류 검증된 records 조회만 노출한다. 기존 unscoped 도구·쓰기·status·검색은 이 연결에 등록하지 않는다. 이는 전체 기능의 대체가 아니라 전체 표면 구현 전 지원 능력을 제한한 단계다. 서버 설정의 principal/agent/session/policy revision을 claim과 별도로 대조하며 관리형 봉인 세대와 공개키 설정을 요구한다. 원문 권한을 검증하기 전에 본문이나 존재 여부를 반환하지 않는다. 운영 resolver·세션 인증·전체 표면 인수 전 운영 완료로 판정하지 않는다.


**2026-09-09 실행 중 정책·키 철회 반영 `867d65b`: [동일 MCP 연결의 설정 변경·조회 중 만료 차단](SCOPED-MCP-POLICY-REFRESH-2026-09-09.md).**
고정된 설정 경로를 조회 전후 다시 읽고 세션/저장소 변경은 거부한다. 키 철회·손상·설정 삭제·조회 중 만료 시 본문 반환을 차단한다. 최종관련30통과/4.31초·Ruff/diff·정적0오류/0경고. 실제 stdio 동일 연결의 변경 거부·복원·재시작 반복을 인수했다. 운영 resolver·나머지 표면·정책 rollback/복구 및 전체 목표는 남는다.


**2026-09-09 제한 검색 `d561f63`: [허용 record 선택 후 limit·실제 서명 검색·새 수집 결손](SCOPED-MCP-SEARCH-2026-09-09.md).**
제한 연결에 sb_search를 추가하고 전체 페이지 범위 검사 후 lexical record를 선택한다. query/limit 서명 결합, 불허 snippet/score 제외. 최종31통과/5.56초·Ruff/diff·정적0오류/0경고, 실제 issuer→stdio 검색2개·limit 변조 거부. 같은 adapter 여러 root가 첫 source만 수집되는 P0 결손을 새로 확인했으며 다음 수정 대상이다. 나머지 운영 목표는 유지한다.


**2026-09-09 JARVIS 파일 정책 `623ef50` / 인수 `79ede52`: [현재 정책·인증 세션 대조 공급자와 실제 MCP 연결](MEMORY-ACCESS-FILE-POLICY-2026-09-09.md).**
소유자 전용 정책 파일을 매 발급 다시 읽고 session/project/method/provider/만료를 대조한다. 누락·손상·철회·불안전 파일은 캐시 없이 거부한다. 관련21통과/13.97초·lint/타입/격리emit통과, 실제 파일 공급자→issuer→stdio 조회/검색 인수. 실제 앱 인증 세션 연결·기발급 claim의 전역 철회 및 전체 운영 목표는 남는다.

## 2026-09-09 제한 응답의 소비자 결합

SB `ec76b14` / JARVIS `8a697d0`: 제한 read/search 응답은 요청 digest와 사용한 claim의 canonical domain digest를 포함한다. 소비자는 별도로 보존한 기대값·claim 만료·fence·record 검증과 예산을 적용한다. 운영 전 제한 프로필의 내부 검증 단계이며 기존 frozen 계약을 완화하지 않는다. 실제 supervised transport 프로필 동결·인증 세션·전 표면 적용은 남는다. [구현과 실제 검증](SCOPED-RESPONSE-CONSUMER-2026-09-09.md).

## 2026-09-09 기존 전송기의 별도 scoped 계약

**2026-09-09 JARVIS `ff0aecc` / SB `687ecf6`:** [고정 scoped 계약→기존 supervised transport→실제 MCP→소비자·재시작 검증](SCOPED-SUPERVISED-TRANSPORT-2026-09-09.md). 전송 관련91통과·SB6통과, 격리 패키징 계약5개 확인. M1 전송 연결은 검증했으며 실제 인증 세션/제품 context 연결·M2~M14와 전체 운영 목표는 남는다. 일반 adapter의 프로필 일괄 전환은 보류한다.

