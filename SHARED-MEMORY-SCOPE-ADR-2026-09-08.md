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
