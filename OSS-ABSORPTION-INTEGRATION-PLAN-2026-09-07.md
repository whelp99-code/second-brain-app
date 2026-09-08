# Second Brain 기반 OSS 장점 흡수 — 통합 분석·구현 계획

기준일: 2026-09-07, 후속 대조: 2026-09-08. 상태: 사용자 확정 방향 병합. R1~R4 및 검색·reader 복구, 자비스 다중 record 소비·명령 완료·삭제 이후 조회·컴파일 중 조회를 보강했다. 최신 코드 대조와 검증은 14절과 구현 원장을 따른다. 전체 인수·운영 배포 완료를 뜻하지 않는다.

인계 원문: [자비스 작업 인계](../Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md).
기존 결함·개선 정본: [24개 항목 분석](IMPROVEMENT-BACKLOG-2026-09-07.md).

현재 읽기용 종합: [인계 재대조·완성 우선 목록](SHARED-MEMORY-COMPLETION-REVIEW-2026-09-08.md). 아래 초반 대조표는 발견 당시 기록이며 후속 구현 상태는 이 종합과 구현 원장을 우선한다.

## 1. 병합한 결정과 범위

1. Second Brain을 유일한 개인·업무 기억 정본으로 유지한다. 기존 CAS·원장·세대·MCP·삭제/복원 구조 위에서 개선한다.
2. **1차 범위는 자비스 + Second Brain + 서로 다른 에이전트의 공통 기억 사용이다.** 기존 I7의 다른 업무 프로젝트/실행자 대량 연결은 후속으로 이동한다.
3. LightRAG, TencentDB-Agent-Memory, code-brain, memory-bank에서 필요한 계약·알고리즘·설계만 흡수한다. 기본 방식은 기존 코드 재사용과 설계 반영이며, 코드 복사나 라이브러리 추가는 파일별 필요성을 확인한 뒤 결정한다.
4. 자비스는 작업 제어·결과 검증, Second Brain은 기억, dev-wiki/Git은 개발 규칙·결정의 원문과 이력을 유지한다. 개발 문서 검색 연결은 정본의 대체나 dev-wiki 전체 자동 색인을 뜻하지 않는다.
5. 별도 기억 서버·에이전트별 기억 DB·모델 Proxy·워커 오케스트레이터·전역 훅을 도입하지 않는다. 사용 에이전트마다 얇은 연결부만 둔다.
6. R1 입력 유실, R2 자비스 해석 실패, R3 요청 기억 복원 실패는 선행 수정·검증했다. 해당 회귀를 유지하고 운영 인수를 이어간다. OSS 채택은 핵심 결함을 우회하는 방법이 아니다.

인계 문서의 '도구 목록이 보이는 것만으로 완료하지 않는다'는 기준은 이번 작업의 R2 재현과 정확히 일치한다. 이전 517개 테스트 통과 및 transport 응답 증거는 보존하되, 공통 기억 완료 증거로 확대 해석하지 않는다.

## 2. OSS별 흡수 결정

공식 README를 인계서의 고정 커밋에서 다시 확인했다. 아래는 채택 제안이며, 우리 환경의 성능 측정 결과가 아니다. 인계서의 일부 핵심 소스·라이선스 조사 결과는 인계 근거로 취급하며 이번에 네 제품을 설치·빌드·벤치마크하지 않았다.

| OSS / 고정 원문 | 선별 흡수할 장점 | Second Brain 적용 지점 | 제외·후순위 |
|---|---|---|---|
| [LightRAG](https://github.com/HKUDS/LightRAG/blob/7eb87008dd84bd26fd69e1459ddb4f19ec1e9784/README.md) | 근거를 보존하는 결합 검색, 삭제 후 파생 인덱스 일치, 검색 평가 | search/hybrid_search/embeddings, generation sealing, 삭제·복원 회귀 검사 | 별도 REST 서버, 그래프 DB, 멀티모달 전체 도입. 관계 확장은 평가에서 이점이 확인된 뒤 |
| [TencentDB-Agent-Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory/blob/220af62226221d7ea07f95aa61eb7c0486cb407a/README.md) | 여러 에이전트가 같은 기억을 사용하는 인터페이스, 범위·상태·출처 개념 | 기존 MCP 프로필, 공통 기억 응답과 프로젝트 범위, capability 지원표 | Core/Hub/Proxy 설치, 모델 인증 경로 교체, 팀 관리 전체 구현 |
| [code-brain](https://github.com/t1seungy/code-brain/blob/8e46f59b3bd7ed08ec9b73ffbc6736717266ffb7/README.md) | 작은 context pack, 단계적 도구 제공, 근거·시점이 있는 결정/실패 기록 | 공통 문맥 선택 서비스, 응답 예산, 도구 프로필, 사용량 관측 | 리포별 별도 .ai 기억 정본, 워커 큐, 전역 규칙·Git 훅 설치 |
| [memory-bank](https://github.com/jung-wan-kim/memory-bank/blob/9ea9b62cf743d1f166e3425d73343532856a90a5/README.md) | 원문으로 돌아가는 사실, 중복·정정·대체 관계, 세션별 중복 주입 방지 | memory_records, source/derivation 원장, conflict/erasure, 문맥 전달 이력 | Claude 전용 훅을 공통 수집기로 취급, 도구 결과 없는 로그를 성공 증거로 사용, 개인 UI/의존성 자동 설치 |

서로 다른 검색·기억 구현을 한꺼번에 붙이지 않는다. 예를 들어 RRF는 이미 있으므로 같은 알고리즘을 외부 코드로 다시 추가하지 않는다. session dedup은 반복 제공을 줄이는 편의 기능이며 기억의 정본이 될 수 없다.

## 3. 기존 구현 대조표

분류: 이미 있음 / 연결·활성화 부족 / 구현 개선 필요 / 신규 필요 / 이번 범위 제외. '이미 있음'은 개념·구현 존재를 뜻하며 해당 기능의 모든 운영 조건을 통과했다는 뜻은 아니다.

| 기능 | 분류 | 현재 근거 | 처리 방침·기존 항목 |
|---|---|---|---|
| 원본 CAS·수집/파생 원장 | 이미 있음 | sb/store/cas.py, sb/store/ledger.py, sb/pipeline.py | 유지. R1의 입력 접수부터 완료까지 보존 보강 |
| generation 기반 단일 writer·읽기 바인딩 | 구현 개선 필요 | sb/generation_runtime.py, sb/generations.py, tests/integration/test_memory_two_process.py | R6/R9/I3. 종료 복구·읽기 가용성 보강 |
| MCP 공통 읽기·접수·상태 API | 연결·활성화 부족 | sb/mcp.py, contracts/second-brain-mcp-v1.json | R2/I1. 실제 자비스 adapter와 다른 클라이언트까지 연결 |
| Claude/Codex/OpenCode/OMO 수집 | 이미 있음 | sb/connectors/sessions_*.py, tests/test_connectors_sessions_a.py | 개별 파서 재사용. 설치·스케줄·정책·실제 로그 호환은 따로 검증 |
| GJC/Orca/project record 수집 | 이미 있음 | sessions_gjc.py, records_orca.py, records_project.py, tests/test_connectors_records.py | 원본 사건·도구 결과의 출처 유지. 이번 범위 밖 실행자 연결은 보류 |
| 인용·record digest·원문 span | 구현 개선 필요 | sb/memory_records.py, sb/request_executor.py | R3/R4. 요청 기반 기억의 복원·시간 의미를 통합 |
| FTS5·짧은 한국어 검색 | 구현 개선 필요 | sb/search.py, sb/sealed_search.py | R5/R7. 필터·결과 단위·페이지 탐색을 고침 |
| cosine + RRF | 구현 개선 필요 | sb/hybrid_search.py:rrf_merge/query_cosine, sb/embeddings.py | R10. sealed 분기 미연결뿐 아니라 query_cosine의 DB 쓰기와 RRF 메타데이터 보존 문제를 개선 |
| 정정·삭제·export·복원 억제 | 구현 개선 필요 | effect_write_requests.py, erasure.py, restore.py, export_retention.py, integration lifecycle tests | 기존 상태기계를 재사용. R3/I2와 결합한 전체 검증 |
| source-level 외부 LLM 정책 | 이미 있음 | Config source policy, pipeline ingest, connector 설정 | 에이전트별 중복 정책 생성 금지. 공통 처리 이전 정책을 유지 |
| 프로젝트/에이전트별 기억 공유 범위 | 신규 필요 | 현재 strict record/read 계약에 일반적인 project/agent scope가 없음 | 버전이 있는 범위 모델. 기존 scope=active/candidate/reference는 지식 상태이며 프로젝트 접근 범위가 아님 |
| 작은 문맥 묶음·세션별 전달 중복 방지 | 신규 필요 | 기존 검색 limit와 자비스 byte budget은 있으나 공통 context-pack/전달 이력 서비스는 확인되지 않음 | G3를 1차 공통 기억 기능으로 상향. 선택과 실제 전달 확인을 구분 |
| 처리/검색 준비 상태·운영 화면 | 구현 개선 필요 | sb/readiness.py, sb/web.py, metrics/status | R8/I6/G5. 기존 화면/API를 개선하며 별도 UI 서버를 만들지 않음 |
| 일반 그래프 검색·멀티모달 확장·팀 관리 | 이번 범위 제외 | 인계서의 조건부/후속 후보 | 근거 있는 검색 평가나 사용자 요구가 생긴 후 검토 |

추가 발견: hybrid query_cosine은 vectors.db에 `knn_out` 테이블을 생성/삭제한다. immutable generation에서 읽기로 연결하기 전에 read-only 쿼리로 바꿔야 한다. rrf_merge는 새 SearchHit를 최소 필드로 구성하여 상태·출처 메타데이터를 잃을 수 있다. 범위 검사는 lexical·vector·관계 확장·원문 읽기에 동일하게 적용해야 한다.

## 4. 공통 기억 사용과 수집·주입의 구분

| 연결부 | 공통 조회 | 기록/변경 | 로그 자동 수집 | 자동 문맥 공급 | 현재 증거·다음 검증 |
|---|---|---|---|---|---|
| 자비스 | adapter 수정·실제 MCP 회수 검증 | CLI 요청→outbox settled→control completed, 삭제 후 64개 record 재저장 검증 | 자비스 사건/결과 계약 담당, 실제 후보 전체 흐름 미완료 | 공통 context pack 미완료 | 운영 구성·배포와 실제 후보/UI 인수는 남음. [최신 검증](MEMORY-READ-FENCE-INTEGRATION-2026-09-08.md) |
| Codex CLI 0.153.4 | 실제 schema5 검색/원문 및 Claude 기억 회수 | 실제 inbox capture·CAS 확인 | 전용 JSONL 파서·fixture 있음; 자동 연결 미검증 | 미완료 | 단일 owner/genesis 격리 인수. GUI·scope·삭제 이후 fence·운영 연결 남음 |
| Claude Code 2.1.261 | 실제 schema5 검색/원문 및 Codex 기억 회수 | 실제 inbox capture·CAS 확인 | 전용 JSONL 파서·fixture 있음; 자동 연결 미검증 | 미완료 | 실제 CLI 상호 회수 통과. scope·자동 수집/주입·운영 연결 남음 |
| OpenCode / OMO | MCP 클라이언트별 설정 실측 필요 | 지원 API 프로필 연결 필요 | 각각 파서·fixture 있음 | 미확인 | 사용 클라이언트와 버전을 먼저 확정 |
| Orca / GJC | 현 실행면·자비스 연결 경로 확인 필요 | 검증 결과는 자비스 경유 원칙 | record/session 파서·fixture 있음 | 미확인 | 기억 접근 지원과 워커 실행 지원을 분리 |
| 기타 MCP 에이전트 | 프로토콜 호환 후보 | 도구 프로필/권한 지원 범위 확인 | 파서가 없으면 미지원 | 자동 주입은 미지원으로 표시 | 목록에 추가할 때 네 열을 각각 실측 |

동일 서버에 접근하는 두 테스트 MCP 프로세스는 교차 연결 회귀 근거가 되지만, 실제 Codex/Claude 앱의 자동 수집·주입까지 검증한 것으로 보고하지 않는다. 사용 중인 최종 클라이언트 목록이 확정되기 전 '모든 에이전트 지원'으로 표시하지 않는다.

## 5. 최소 공통 계약 제안

아래는 필드 의미 설계이며 확정된 wire schema나 신규 authority 체계가 아니다. 기존 frozen schema 4의 해시·도구 목록을 임의로 변경하지 않는다.

- **출처/범위:** 기존 source ID·URI·버전·content digest·record ID를 유지하고 project_id, producer_agent, origin_session/event를 명시적으로 연결한다. producer_agent는 출처이지 자동 접근 권한이 아니다. 단일 사용자 안에서 프로젝트 공유 범위를 먼저 해결한다.
- **접수/완료:** 기록 접수 ID, 처리 상태, 결과 record/generation을 연결한다. inbox 접수와 승인된 request 효과는 기존 의미를 유지한다. 'accepted'를 '사용 가능한 기억'으로 표시하지 않는다.
- **사실/증거:** 원문·인용·수집 시각·검증 주체·작업 결과를 구분한다. 실패·미확정 tool result에서 성공 사실을 생성하지 않는다. 자비스 실행 결과 검증을 Second Brain LLM 요약으로 대체하지 않는다.
- **시간:** record validity, observed_at, review_due, response freshness를 분리한다. 최신 조회라고 사실 자체가 다시 유효해지는 것은 아니다. R4가 선행이다.
- **문맥 요청:** query/task, 허용 프로젝트 집합, 세션 식별자, 예산, 최신성 요구를 받는다. 호출자가 문자열로 주장한 범위만으로 접근을 허용하지 않는다.
- **문맥 응답:** 선택한 record ID·digest·generation·근거·최신성·충돌 상태, 포함/제외 이유, 실제 크기와 예산 절삭 결과를 반환한다. 토큰 수는 tokenizer를 명시하며 공통 강제 한도는 바이트로도 검증한다.
- **중복 제공:** session + record identity/version + 문맥 재설정 구간을 키로 삼는다. 선택만 하고 실제 주입에 실패한 결과를 '전달 완료'로 기록하지 않는다. 수정된 기억은 다시 공급하고, context compaction 후 필요한 기억을 영구적으로 억제하지 않는다.
- **프로필:** 자비스 기존 strict 프로필은 호환성을 유지한다. 새 context/capability 도구는 새 negotiated profile 또는 합의된 차기 계약에서만 노출한다. 모든 에이전트에 모든 쓰기 도구를 기본 노출하지 않는다.

세션별 전달 이력은 bounded/만료 가능한 운영 자료다. 에이전트 로컬 사본이 필요해도 재생성 가능한 캐시/receipt에 한정하며 기억의 정본과 별도 정책을 만들지 않는다.

## 6. 통합 구현 순서와 완료 증거

| 단계 | 기존 항목 | 바꿀 지점·삭제할 중복 | 통과 조건 |
|---|---|---|---|
| 0: 입력 보존 | R1 | generation inbox 일괄 삭제 제거만으로 충분하지 않음. inbox adapter가 scan 중 선제 .done 이동하는 점도 함께 수정. 접수→원장 확정 이후에만 완료 처리 | limit·다른 명령·실패·재시작에서 미처리 기록 보존 |
| 1: 자비스 최소 순환 | R2/R3/R4/I1 | MCP의 저장 메타데이터 노출 정리, request 기억의 출처/복원 통합, 시간 계약 조율. 자비스 결함을 SB monkeypatch로 우회하지 않음 | 실제 생성 페이지→자비스 adapter, 요청 receipt→완료→재조회, 다음 날 기억, backup/restore |
| 2: 두 에이전트 공통 접근 | R5/R6/R9/I7 전반부 | capability 지원표·얇은 연결부·범위 계약. 별도 DB/파서/정책 중복 설치 금지 | A 기록→B 원문/프로젝트/버전 회수. 두 writer 동시 요청도 기존 single writer 경로에서 유실·중복 없음 |
| 3: 문맥 공급 | G3 상향, G1/G4 일부 | 공통 selection 함수와 bounded 전달 이력, 예산·최신성·정정/삭제 반영 | 반복 요청 중복 공급 감소, 변경 record 재공급, compaction/주입 실패 재시도, 범위 밖 노출 0 |
| 4: 검색 품질 | R7/R10/G2 | 기존 FTS/cosine/RRF 재사용. immutable 읽기와 메타데이터 보존, 동일 범위 필터 | 고정 한국어 질문 세트에서 근거 회수·지연·오래된 정보 노출 비교. 향상 없는 단계 비활성 |
| 5: 운영 완성 | R8/I2~I6/I8/G5 | 기존 readiness/UI·배포 자산·복구 절차 보강 | end-to-end 가시성, 깨끗한 런타임 복구, 반복 실행/부하 증거 |
| 후속 | I7 업무 실행자 연결, G6 확대 | 메일·기술·문서 등 별도 업무 실행자 연결 | 1차 공통 기억 완료 후 하나씩 검증 |

이 순서는 새 기능 24개를 추가하는 것이 아니다. 기존 24개 항목에 인계의 출처·지원 범위·완료 조건을 병합하고 G3 및 공통 에이전트 접근의 우선순위를 올린다.

## 7. 자비스와 조율할 사항

- R2: 내부 derivation_key의 보존 위치와 public frontmatter 투영을 먼저 합의한다. 파서의 strict 검증이나 계약 해시를 완화하지 않는다.
- 추가 자비스 결함: `second-brain-evidence-parser.ts:235`의 resolveDuplicates는 page_id + sid로 묶어 같은 출처의 서로 다른 record를 충돌로 분류한다. 앞선 R2 진단에서 derivation_key만 메모리상 제거했을 때 conflicts가 반환된 이유와 일치한다. 출처 하나에 정상 문장이 여러 개인 경우와 실제 상충 사실을 구분하도록 자비스 작업에서 수정해야 한다.
- R4: 하루 validity와 자비스 evidence expiry를 함께 수정하는 계약이 필요하다. 장기기억·임시 상태·응답 freshness 테스트 벡터를 공유한다.
- 프로젝트 scope·context pack·delivery receipt 추가는 프로필/버전 변경으로 제안한다. 현 schema 4에 도구를 조용히 끼워 넣지 않는다.
- 인수 증거는 요청 ID, record ID/digest, generation, 출처, adapter verdict, 저장 상태, 재조회 결과다. 프롬프트 원문·키·민감 콘텐츠를 진단 로그에 중복 저장하지 않는다.
- 자비스 내부 실행 lease·명령·task schema·readiness 결함은 자비스 작업이 담당한다. Second Brain 작업에서 우회 실행자를 만들지 않는다.
- 전달물은 이 계획과 후속 검증 보고서 파일이다. 이후 사용자의 연동 완성 지시에 따라 자비스의 기억 소비 결함도 해당 리포의 좁은 수정으로 해결한다. 자비스의 무관한 변경은 보존하고 외부 메시지는 발송하지 않는다.

## 8. 검증 행렬

공통 회귀 행렬은 `입력 경로 × 소비 연결부 × lifecycle × 장애 지점`이다. 대표 시나리오는 다음과 같다.

1. CLI/inbox/업로드/승인된 request 각각의 접수 → 수집 → 기억 → 자비스 해석.
2. 서로 다른 두 에이전트의 실제 설정으로 A 기록/B 조회 및 B 정정/A 재조회.
3. 동일 원본·요청 재전송, capped 수집, parser/CAS/LLM 실패, 프로세스 종료와 재시작.
4. 다음 날·30일 뒤 회수와 임시 사실의 만료. 미래 시각·상충 출처도 포함.
5. 프로젝트 X 자료가 허용되지 않은 Y 검색·벡터·관계 확장·원문·context pack 경로로 새지 않음.
6. 기억 정정·삭제가 lexical/vector/context receipt에 반영되고 복원·재색인 후 재유입되지 않음.
7. 갱신 중 읽기, 두 작성자 요청, client disconnect, reader 종료 시 데이터 보존.
8. context 중복 요청·compaction·전달 실패·정정된 record 재공급과 예산 준수.
9. 실패/미확정 실행 로그가 성공 교훈으로 승격되지 않음.

자동 fixture, 실제 MCP 프로세스, 실제 에이전트 앱, 실제 자비스 업무 순환을 각각 다른 검증 수준으로 기록한다.

## 9. OSS 출처 관리와 현재 작업 상태

현재는 설계 참고이며 외부 코드를 복사하거나 네 제품을 설치하지 않았다. 인계서의 라이선스 표기는 LightRAG/TencentDB-Agent-Memory/memory-bank MIT, code-brain Apache-2.0이다. 실제 채택 시 각 파일의 고정 커밋·라이선스·저작권·변경 내용·해당 NOTICE를 별도로 확인하고 기록한다. README 소유자와 설치 스크립트 업데이트 소유자가 다른 code-brain 경로를 자동 실행하지 않는다.

이번 분석이 구조 변경 ADR 채택을 뜻하지 않는다. 자비스/dev-wiki 역할 변경은 필요하지 않으며, 이후 구조를 변경할 경우 기존 dev-wiki 절차에 맞는 결정 초안을 마련한다.

## 10. 이번 구현·검증 결과

R1 입력 보존을 기존 코드에서 수정했다. `AcknowledgingSourceAdapter`는 추가 서버나 큐가 아니라 커넥터의 선택적 완료 통지 인터페이스다.

- inbox scan은 파일을 이동하지 않는다. 파이프라인이 CAS 존재와 원장 transaction 확정을 확인한 뒤 해당 SourceRef 버전만 acknowledge한다.
- acknowledge 시 실제 파일 버전을 다시 비교하여 scan 이후 수정된 입력은 이동하지 않는다.
- generation 변경은 inbox 전체 대신 완료가 확인된 `.done` 잔여물만 정리한다. 다른 명령·부분 수집·CAS 실패에서 pending 입력은 보존한다.
- 수정 파일: `sb/connectors/base.py`, `sb/connectors/inbox_documents.py`, `sb/pipeline.py`, `sb/generation_runtime.py`. 커넥터 레지스트리 `__init__.py`는 수정하지 않았다.
- 회귀 검증: 재시도 후 pending 보존, capped 수집의 다음 실행 재개, CAS 실패 후 재수집, scan 이후 변경 파일 보존. 기존 connector scan 테스트는 명시적 완료 통지를 검증하도록 바꿨다.
- 전체 테스트: `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py` → **520 passed, 2 skipped**.
- `uv run ruff check sb tests` 통과. `uv run basedpyright sb tests` 오류 0, 경고 60. `git diff --check` 통과.
- 로그·변경 전 스냅샷: `/var/tmp/sb-oss-integration-20260907/`.

**적용 범위는 현재 작업공간의 소스와 테스트다. 운영 release 전환·서비스 재시작·외부 OSS 설치·코드 복사·Git push는 이번에 하지 않았다.** R2/R3/R4 및 실제 두 에이전트 앱의 공통 기억 인수 검증은 미완료다. 다음 구현은 R2 공개 페이지 투영과 자비스의 record 중복 판정 조율, R3 저장/복원 출처 계약 통합이다.


## 11. B1 후속 구현

[구현 원장](IMPLEMENTATION-STATUS.md)에 후속 커밋과 실측을 병합했다. R2 공개 metadata/논리 ID 투영 및 R3 CAS·요청 출처·정정 후 인용 일관성을 수정했다. 실제 단일 기억의 MCP→기존 자비스 adapter 소비는 current, 전체 Python 검사는 527 passed/2 skipped다. R4와 다중 record 소비, 실제 자비스 전체 업무 순환, 에이전트 앱 교차 사용은 계속 미완료다. OSS 외부 코드를 복사하거나 의존성을 추가하지 않았다.

## 12. 추가 분석 병합 — 공통 기억 소비와 시간

11절은 당시의 중간 관측이다. 후속으로 자비스 소비부에서 다음 세 지점을 고쳤다.

- 페이지 parser와 결과 집계의 중복 기준을 bound record ID/digest로 변경했다. 같은 sid는 같은 출처라는 뜻이며, 서로 다른 사실이 충돌한다는 뜻이 아니다. legacy page/sid 판정은 유지한다.
- 검색은 page별 모든 record 선택을 보존한다. 페이지를 한 번 읽고 모든 ID/digest를 검증한다. 마지막 선택으로 앞선 선택을 덮어쓰던 유실과 검증 누락을 제거했다.
- R2 자비스 커밋은 `5c44b1f`. 실제 MCP와 빌드한 자비스 adapter로 운영 자료 `운영 복구`를 current로 회수했다. 같은 페이지의 여러 기억과 중복 선택은 회귀 테스트로 검증했다.

R4는 다음처럼 의미를 분리했다. 자세한 경계·배포 조건은 [시간 계약](MEMORY-TIME-CONTRACT-2026-09-07.md)을 따른다.

| 시간 | 의미 | 구현 처리 |
|---|---|---|
| record valid_from / valid_until | 저장된 주장의 적용 구간 | 내부 명시값을 검증·보존. 종료일이 없다는 이유로 다음 UTC 자정에 폐기하지 않음 |
| 날짜 미상 | 시작/종료를 모름 | 문서화된 열린 경계로 표현. 조회 시계나 합성 Git commit 시각을 관측일로 만들지 않음 |
| observed_at | 이번 조회 시각 | record identity와 분리 |
| fresh_until / expires_at | 소비자가 이번 조회 결과를 사용할 수 있는 시간 | 조회 시각 + 설정 TTL, 명시적 종료일로 상한 제한 |
| 재검토·현실 검증 | 사실이 현재도 참인지 확인한 근거 | 현재 조회가 이를 대체하지 않음. untrusted/authority none 유지. 기억 유형별 정책은 B5 |

실제 소스 MCP → 자비스 adapter에서 `업무` 10개가 current로 회수됐다. 소비자 시계를 현재/다음 날/35일 뒤로 주입한 검사에서도 같은 record ID 10개와 유한한 응답 TTL을 확인했다. 이는 미래 시점 모의 검사이며 35일 운영 실적이 아니다. 실제 업무 검증→candidate→outbox→settled→재사용 순환과 실제 서로 다른 에이전트 앱의 공유 검증은 별도로 남아 있다.

다음 순서는 **B4 실제 자비스 저장·재사용 순환 → 프로젝트 범위·두 에이전트 접근 → B5 문맥 공급 → B6 운영 전환·복구 → B7 검색/부하 평가**다. I3 잠금 지연은 B4와 함께 해결해야 하는 가용성 조건이다. R10 hybrid는 기존 구현의 읽기 전용화와 평가에서 이점이 확인된 뒤 활성화한다. 네 OSS 전체 설치·Proxy·별도 기억 DB·그래프 서버는 계속 보류한다.

## 13. 2026-09-08 인계 재대조 및 우선 실행 목록

인계 문서의 2026-09-08 갱신본을 다시 대조했다. 전달 도구 실패에 관한 발신 작업 이력은 제품 결함으로 넣지 않는다. 핵심 결정인 Second Brain 유지·네 OSS 장점 선별 흡수·자비스/여러 에이전트 우선은 기존 1~3절과 일치하므로 별도 서버 도입이나 정본 이전을 추가하지 않는다.

현재 소스의 저장·재조회 경로는 격리 실제 MCP에서 동작한다. **운영 공통 기억 장소 전체가 완성됐다고 판정할 수는 없다.** 64개 record 및 민감도 검증의 변경·재현·음성 검사는 [결과 대응 계약](REMEMBER-ARTIFACT-CONTRACT-2026-09-08.md)에 있다. 다음은 기존 항목과 합친 실행 목록이다.

| 우선순위 / 관점 | 남은 작업과 영향 | 구체적 개선 및 완료 기준 |
|---|---|---|
| P0 수정 — 자비스 자동 연결 | CLI/dashboard·주기 실행·control completed·기본 signed fence를 격리 MCP에서 검증 | I1-a/c/e: 후보/publication/UI 전체 흐름과 운영 구성·배포 인수 진행. 최신 결과·우선순위는 [삭제 이후 조회 보고서](MEMORY-READ-FENCE-INTEGRATION-2026-09-08.md) |
| P0 수정 — 승인 rollback 복구 | 316b8f2 소스 수정·격리 실제 MCP 검증 완료, 운영 미반영 | I1-b: event/바깥 transaction 실패 후 원문 보존·새 receipt 재발행 검증. 영속 권한/변경 파일 보존. 운영 반영은 B6에서 확인 |
| 소스 완료 / 운영 P1 — 갱신 중 읽기 | I3의 LLM 준비 중 조회 차단 및 조회 진입 유지보수 대기를 수정 | writer mutex/SH 준비/EX 전환, 실제 자비스 동시 조회와 writer kill·삭제 원장 변경 검증. 대표 데이터 p95와 운영 인수는 [후속 보고서](GENERATION-READ-CONCURRENCY-2026-09-08.md) |
| P1 개선 — 일상 입력과 정정 | 일반 Enter 여러 줄 미지원, V1 owner correct 승인 대상 결합 부족 | 버전이 있는 본문 계약과 기존 V2 target/delegation 정정을 연결. 원문 전체 대응 및 승인 후 대상 변경 거부 검사 |
| P1 개선 — 에이전트 공통 사용 | 두 MCP 프로세스 검증은 실제 다른 앱의 저장·주입 지원 증거가 아님 | 실제 Codex/Claude 등 사용 클라이언트별 읽기·쓰기·수집·주입 지원표, A 저장→B 출처/버전 회수 실사용 검증 |
| P1 개선 — 프로젝트 범위 | sensitivity와 지식 상태 scope만으로 접근 범위를 제한할 수 없음 | 공통 project/user/agent 범위 계약과 버전 호환. 검색·원문·관계 확장 모두 범위 밖 거부 검사 |
| P1 고도화 — 문맥 공급 | 검색 limit만으로 세션 중복·compaction 후 재전달을 관리하지 못함 | B5: 관련도/분량 제한, 근거·버전·선택 이유, 실제 전달 receipt와 중복/재시도. 실패·미확정 실행을 성공 기억으로 승격하지 않음 |
| P1 개선 — 운영 복구와 가시성 | 소스와 release 차이, 과거 generation 잔여물, 백업 복원 신뢰성 | B3/B6: 원장·디렉터리 대조, 독립 복원 검사, readiness·오류·백업 시각 표시. 실행 파일과 provider generation의 함께 전환/복구 검증 |
| P2 고도화 — 한국어 검색 품질 | 외부 프로젝트 README 성능은 현재 시스템 성능 근거가 아님 | B7: 한국어 고정 질문 100~300개, 근거 회수·오래된 결정 노출·지연·분량 평가. 5천 파일/10만 unit/1만 페이지 및 100회 반복 목표 실측 |
| 조건부 고도화 — hybrid | 기존 RRF/벡터 코드의 sealed 읽기 쓰기 부작용·메타데이터 손실 | B8: 읽기 전용·출처/범위 보존부터 수정 후 같은 질문 기준선과 비교. 이점이 확인될 때 활성화 |

검증된 변경은 기능 단위로 커밋하고 운영 반영 여부를 별도 기록한다. 신규 OSS 코드를 복사하지 않았으므로 이번 단위에서 외부 파일 라이선스 고지 추가는 없다. 향후 복사 시에는 인계서 기준의 파일·커밋·라이선스/NOTICE를 기록한다. 계획의 네 제품 비교는 고정 커밋 인계 자료이며 최신 upstream 재조사·실측을 의미하지 않는다.

## 14. 현재 소스 재대조와 작업별 인수 조건

2026-09-08 사용자 인계 재확인. Second Brain 기준 소스 `ee4fc13`, 자비스 HEAD `e61893e`. 자비스에는 별도 작업의 task 실행·Git publication 관련 미커밋 변경이 있으므로 이번 대조를 자비스의 깨끗한 커밋 전체 검증으로 표현하지 않는다. 이번 단위는 세컨드브레인 작업공간의 분석·계획 갱신과 기존 구현 재검증이며, 아래 남은 기능을 새로 구현했다는 뜻은 아니다.

### 현재 동작 판정

저장 엔진·자비스 소비·완료 상태 연결은 격리 실제 프로세스에서 통과했다. 입력/CAS/인용/복원, 여러 record의 동일성, 시간 의미, 검색 필터, reader 복구, 삭제 이후 서명 조회, 컴파일 준비 중 조회의 기존 수정을 재사용한다. 반면 실제 사용자 후보와 앱에서 시작하는 흐름 및 운영 서비스 인수는 남아 있다. 저장소 완성률을 테스트 개수로 환산하지 않는다.

### P0 후보 화면 연결의 구체적인 공백

| 현 코드에서 확인한 사실 | 사용자에게 미치는 영향 | 재사용할 구현과 필요한 연결 |
|---|---|---|
| 자비스 `dashboard/src/memory-candidates.tsx`는 종류·작업·민감도·이유·보존일만 렌더링 | 후보를 열어 원문·출처를 검토하거나 화면에서 확인/거절할 수 없음 | 기존 후보 상세 read API와 제공된 actions를 연결. 목록에 원문을 무조건 추가하지 않고 상세 조회 수명과 정리 정책 유지 |
| `src/dashboard/memory-mutation-routes.ts`에 `candidates/:id/actions/stage-decision`이 있지만 `dashboard/src/memory-api.ts`에 호출 메서드가 없음 | 후보 결정 백엔드가 있어도 기억 화면에서 사용할 수 없음 | 기존 stageCandidateDecision과 approvals 흐름 사용. 후보 변경·만료·원문 소실 오류 및 재시도 표시 |
| `stageMemoryRememberDispatch`의 제품 호출자는 현재 `src/cli-control-commands.ts` | 후보 확인 뒤 publication이 생겨도 화면에서 저장 명령 준비까지 이어지지 않음 | `src/memory-remember-dispatch.ts`의 영속 authority 검사·expected artifact·멱등 command ID 재사용. 별도 서명/승인 구조나 임의 자동 승인 추가 금지 |
| `dashboard/src/memory-api.ts`의 effects 조회는 `operation=export`와 네 상태만 요청 | 기억 화면에서 remember 저장의 접수·진행·완료·실패를 추적하는 연결이 부족 | 기존 control/outbox 상태를 request ID에 연결해 조회. remember가 export effects API에 이미 있다고 가정하지 않음. accepted/pending을 completed로 표시하지 않음 |

이 네 항목은 **제품 코드 확인**이며 실제 브라우저 클릭 재현 결과는 아니다. 인수 테스트는 실제 후보 생성→상세 검토→기존 사용자 확인→저장 명령→provider proved→outbox settled→control completed→다음 조회의 같은 record·출처 회수까지 이어져야 한다. 새로고침·중복 클릭·명령 재시도·권한 만료·저장 실패에서 중복 효과 0과 정확한 상태 표시를 확인한다. 자비스의 독립 실행 결과 인증 작업은 별도로 진행 중이므로 그 결과 계약을 대조해 후보 수집에 연결하고 요약문을 성공 증거로 대체하지 않는다.

### 수정·개선·고도화 실행 목록

아래는 기존 24개 ID를 세분한 실행 단위다. 중복된 새 백로그를 만드는 것이 아니며 우선순위는 1차 공통 기억 완성에 따른다.

| 순서 / 분류 / 기존 ID | 구현할 범위와 책임 | 완료 증거 |
|---|---|---|
| 1 / P0 개선 / I1·G5·G6 | 위 후보/UI 네 연결. 자비스가 수집·검증·확인·명령을 담당하고 SB는 저장/조회 계약 유지 | 실제 입력 하나의 후보·명령·요청·결과 ID 연속 추적. 실패/미확정 결과는 성공 기억으로 승격되지 않음 |
| 2 / P1 개선 / I1·G4 | 일반 Enter 입력과 V2 정정. `mcp_write_models`, frozen 계약, 자비스 본문/target 소비를 버전별 대조 | CR/LF·반복 문장·공백·인용이 있는 원문 전체 대응. 승인 후 대상 교체 거부, 정정된 사실 회수 및 이전 출처 추적 |
| 3 / P1 개선 / B4·I7 | 실제 Codex/Claude 등 클라이언트 연결. 기존 MCP 프로필·에이전트별 connector 재사용 | A 기록→B 동일 record·원문·버전 회수. 조회/쓰기/수집/주입을 각기 지원·미지원·미검증으로 표시 |
| 4 / P1 신규 개선 / B4·I7 | 공통 프로젝트/사용자 범위와 생산 에이전트 출처. 기존 schema4에 없는 범위 계약을 버전 관리 | 허용 범위 밖 자료가 검색·직접 page 조회·후속 확장 어디서도 노출되지 않음. producer_agent를 접근 권한으로 취급하지 않음 |
| 5 / P1 고도화 / G1·G3·G4·G6 | 기억 유형·시간·근거, 작은 문맥 선택과 세션 전달 이력. 공통 범위 확정 후 적용 | 바이트/토큰 예산, 제외 사유, 실제 전달 receipt. 수정된 기억 재전달, compaction/전달 실패 후 재시도, 오래된 결정 구분 |
| 6 / P1 수정 / R6·I3 | writer 종료 후 과거 `.staging`/미활성 세대와 원장 대조. SB generation runtime/ops | active·reader·pending 요청·삭제 증거에 필요한 자료 보존. 복구 재실행 수렴. 오래되었다는 이유만으로 일괄 삭제하지 않음 |
| 7 / P1 수정 / I1·I2·G5 | 자비스의 서명된 export 수명 상태 소비. `second-brain-effect-service`, lifecycle observer/export store 대조 | provider identity·request·manifest·서명·expires_at 대응. 만료/철회/삭제된 export를 available로 표시하지 않고 물리 폐기 전 완료를 주장하지 않음 |
| 8 / P1 수정·개선 / R8·I2·I4·I6 | SB readiness와 검증된 백업, 릴리스·설정·세대의 전환/복구 | 오래된 성공·손상 backup/journal·정체 요청의 degraded 사유. 깨끗한 런타임 복원 후 읽기/쓰기, 삭제 기억 부활 0, rollback 실측 |
| 9 / P2 개선 / I8·I5·G2 | 최근 변경 평가의 시계 일치와 예상 record 검증, 재현 설치·타입 경고·부하·한국어 검색 평가 | 빈 changes의 current를 회수 성공으로 오판하지 않음. 고정 100~300문항 및 계획 규모/100회 반복의 근거 회수·지연·성장량 |
| 10 / 조건부 고도화 / R10·B8 | 기존 cosine/RRF의 읽기 전용화와 메타데이터 보존, 이후 hybrid 연결 판단 | 조회 전후 인덱스 불변, 범위·출처 보존, lexical 기준선 대비 품질/비용 이득. 효과가 없으면 비활성 유지 |

7번의 구체적 근거: 자비스 `second-brain-effect-service.ts:requestStatus`는 상위 schema/request/state를 확인하고, lifecycle observer는 proved/proof를 소비한다. export store의 자체 만료 처리만으로 SB의 서명된 export lifecycle 검증을 대체할 수 없다. SB의 `EXPORT_EXPIRED` 거부와 물리 정리 회귀가 통과해도 양쪽 export 사용자 흐름의 완료 증거는 아니다.

8번의 현재 근거: `sb/readiness.py`는 최근 백업 파일 mtime을 사용하며 검증 receipt를 확인하지 않는다. 마지막 실행의 경과 시간과 오래 정체된 요청도 준비 상태에 충분히 반영하지 않는다. 상태 명령의 성공을 복원 가능한 백업의 증거로 사용하지 않는다.

10번의 현재 근거: `sb/hybrid_search.py:query_cosine`은 `knn_out`을 DROP/CREATE하고 `rrf_merge`는 네 필드로 SearchHit를 재생성한다. 이 경로를 sealed generation에 곧바로 연결하지 않는다. 외부 LightRAG 코드 도입보다 이 기존 읽기 부작용과 출처 보존 문제를 먼저 해결한다.

### 이번 재검증과 한계

- `TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py`: **564 passed, 2 skipped, 137.99초**. `/var/tmp/sb-handoff-refresh-tests.log`.
- `uv run ruff check sb tests`: 통과. optional embeddings extra의 전체 검증과 실제 모델 품질 평가는 포함하지 않는다.
- 다음 실제 MCP/JARVIS 하네스 통과. `/var/tmp/sb-handoff-refresh-acceptance.log`.

```bash
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs ../Orca-JARVIS --owner-confirmed --approval-rollback --runtime-cli --record-limit --record-budget --sensitive --after-delete --during-compile
```

결과는 control completed, provider proved, outbox settled, sensitive record 64개, 두 클라이언트 current, rollback 복구, replay 후 추가 dispatch 0, review 원문 0개, cleanup/control 오류 없음이다. 삭제 sequence 1 이후 무서명·과거 fence는 각각 거부됐고 삭제 record 회수는 0개였다. 컴파일 준비 중 완료 확인과 두 클라이언트 조회 묶음은 약 **1.384초**였다. 단일 요청 지연이나 p95 수치가 아니다.

합성 owner 입력/승인과 격리 vault를 사용한 실제 프로세스 통합 검사다. 실제 사용자의 업무 결과, Codex/Claude 앱 화면, 운영 설치·수집·주입을 검증한 것은 아니다. 최신 upstream 기능·라이선스를 재조사하거나 외부 코드를 복사하지 않았다. 이번 단위에서 서비스 재시작·배포·활성 세대 전환·push와 자비스 제품 소스 수정은 하지 않았다.


## 15. 후보 UI 공백 구현 후 갱신

14절의 P0 네 공백은 후속 구현으로 연결했다. 상세 검토 API·digest를 결합한 확인/거절·기존 승인 흐름·저장 명령 준비·request별 진행 표시가 있다. 실제 브라우저에서는 검토→서명 fixture 승인 실행→저장 pending→새로고침 유지를 확인했고, 별도 실제 MCP 인수에서는 provider proved→outbox settled→control completed→dashboard stored=true 및 두 클라이언트의 64개 record 회수를 확인했다. 브라우저 전체 경로가 실제 provider 저장까지 완료됐다는 주장과 구분한다.

remember 확인 실행기가 correct 경로로 실패하던 결함과 Overview의 비동기 진단 중 정상 외부 DB 변경을 쓰기로 오판하던 결함도 수정했다. 기존 후보·원문·권한·outbox를 재사용했으며 신규 OSS 서버와 frozen MCP 변경은 없다. 변경·회귀 수치·화면 증거·경계는 [후보 UI 인수 보고서](JARVIS-MEMORY-CANDIDATE-UI-2026-09-08.md)를 따른다.

14절 실행 목록 1번의 실제 사용자/업무 결과 후보 수집은 아직 남는다. 자동 요약을 검증된 실행 결과로 취급하지 않는다. 다음 순서는 **실제 후보 수집 → 일반 입력/V2 정정 → 앱별 공통 접근·범위 → 문맥 예산·전달 이력 → 운영 복구·한국어 검색 평가**다. 2~10번의 미완료 판정과 위험 보류는 유지한다. 이번 소스 검증으로 B4 전체나 운영 설치 완료를 선언하지 않는다.


## 16. 후보 접수 경로와 실제 시각·재시도 보강

기존 분류기의 제품 호출 부재를 CLI 파일 접수로 연결했다. 같은 writer transaction의 계산으로 원문/DB를 결합하며 권한을 실제 시각으로 재검증하고, 유효한 동일 미커밋 원문만 복구한다. CLI 접수→owner 확인→실제 MCP 저장→64개 record 재조회→dashboard 저장 완료를 검증했다. [후보 접수 보고서](MEMORY-CANDIDATE-INTAKE-2026-09-08.md).

실제 task completion은 자비스 `7129b9d`로 확정돼 해당 source/검증 결합을 다음으로 진행한다. 기존 verified authority를 CLI 주장으로 새로 발행하지 않는다. approved/no_data 본문 인계는 별도 미완료이며 실제 앱 수집/주입·범위와 나머지 B5~B8 순서는 유지한다.

## 17. 작업 원본 차단 전파 보류와 기존 검색 선행 수정

task completion 대조에서 신규 요약은 기존 labeled_inference로 취급해야 함을 확인했다. collector 초안의 독립 소스 검토에서 task_id 차단 누락과 생성 후 원본 차단의 후보·승인·저장 전파 부재를 확인하여 제품 소스 반영을 보류했다. 자비스 `73d59df`의 [재개 계약](../Orca-JARVIS/docs/planning/task-memory-source-privacy-hold.md)에 수집 전/후·승인 후·전송 중·저장 후/복원까지의 회귀 조건을 기록했다. 작업 완료 인증이 요약문 검증을 대신하지 않는다.

독립적으로 진행할 수 있는 R10의 기존 조회 부작용·RRF 출처 유실·모델 identity·결과 구분자 결함을 수정했다. [읽기 전용 검증 보고서](HYBRID-READONLY-2026-09-08.md). 이는 LightRAG식 검색 확장 전 선행 보강이며 새 OSS 도입이나 sealed hybrid 활성화가 아니다. cosine 전용 메타데이터·동일 세대·범위/삭제 수명·평가를 계속 요구한다.

우선순위는 자비스 공통 기억 완성으로 유지한다. 작업 수집은 원본→파생 기억의 차단 전파 계약을 먼저 확정하고, 기존 제품 접수/검토/저장 흐름은 계속 사용한다. 일반 입력/V2 정정·앱별 공통 범위·문맥 예산/전달 이력·운영 복구/품질 평가의 미완료 판정을 유지한다.

## 18. 기존 V2 정정의 여러 줄 원문·인용 회수 보강

실제 V2 정정에서 CRLF를 LF로 바꾸어 artifact proof가 실패하고 중간 문장 인용이 빠지는 결함을 확인해 수정했다. 원문 digest와 frozen wire는 유지하고 문장별 인용 렌더링·effect snapshot·완료 관측을 일치시킨다. record 수/바이트 초과는 대상 쓰기 전에 검사한다.

빈 줄·LF/CRLF·반복·인용 문자를 포함한 4개 문장의 실제 provider proved→서명/관측 검증→두 자비스 MCP 클라이언트 current와 내용·출처 일치를 확인했다. [상세 보고서](CORRECTION-RENDERING-2026-09-08.md). V1 신규 기억의 일반 줄바꿈과 자비스 정정 UI/승인/saga 전체 인수는 완료로 계산하지 않는다. 다음 I1-d/G4의 작업은 이 두 경로의 제품 계약과 완료 상태 연결이다.


## 19. I1-d/G4 후속 — 정정 완료의 자비스 상태 연결

SB `ec2a758`의 여러 줄 정정과 자비스 production lifecycle을 실제 MCP로 연결했다. provider proved와 control completed 사이의 중단/만료 복구를 구현했다. 이전 18절에서 미완료였던 backend saga/control 연결은 격리 인수를 통과했다. 정정 UI와 실제 앱·운영 전환은 계속 미완료다.

수정·개선 항목: 원문 없는 원 명령 binding, 원 승인/redemption/전송 fence 검증, signed proof와 동일 lane purge 검증, 원장/효과/event의 atomic 완료, completed purge의 offline 재사용, bounded cursor 복구와 cursor 실패 rollback, compaction 이후 clock 재조회. 새 회귀 11개 포함 관련 34개 통과; 실제 event 실패 후 20분 재개에서 provider 추가 호출 없이 completed, 두 클라이언트 같은 정정 기억 4개, 이전 기억 0개, 전송/compaction 각 1회.

[상세 보고서](CORRECTION-CONTROL-COMPLETION-2026-09-08.md)의 다음 항목을 기존 R/I/G 목록에 합친다. V1 일반 LF·정정 UI·실제 앱별 공유·context pack/범위·readiness/운영 복원·검색 품질 순으로 남은 경계를 검증한다. task 수집은 원본 차단 전파 계약이 갖춰질 때 재개한다. OSS별 별도 정본/서버/승인 체계를 추가하지 않는다.


## 20. R8/I6 후속 — 정본 기억의 운영 준비 상태

공통 기억 순환의 운영 인수 선행 조건으로 백업 검증과 readiness를 보완했다. 최신 tar.gz의 mtime만 보는 경로를 검증된 archive identity/원 저장소·provider/삭제 이력 검사로 바꾸고, stale run·정체 요청·최근 실패·손상 journal·세대 정리 지연을 반영한다. 기존 복원 검사와 generation/request lock을 재사용한다.

표준 전체 591 passed/2 skipped, 실제 CLI/HTTP에서 검증 전 503→검증 후 200→손상 후 503, health 200 유지와 managed backup identity를 확인했다. [상세 보고서](READINESS-VERIFICATION-2026-09-08.md). 이 검증은 fixture 기반 실제 CLI/서버 인수이며 운영 전환은 아니다. 기존 업무 결과 수집 차단 전파·실제 앱별 공급·문맥/범위·검색 품질과 운영 runtime 복원 완료 조건은 유지한다.

## 21. I1-d 후속 — 본문 계약의 실제 양쪽 대조

자비스 `30e2024` 커밋을 격리 빌드하고 실제 Python V1 접수와 자비스 요청/후보 본문 검증기를 12개 입력으로 비교했다. LF/CRLF/CR/탭은 모두 거부한다. 선행 BOM은 provider만 허용하고 선행 NEL은 자비스만 허용한다. 65개 record와 인용 이스케이프 뒤 크기 초과는 후보 본문 검사를 통과하지만 양쪽 요청 경계에서 거부된다. 수락 4개는 원문 보존·정확 재시도, 거부 8개는 요청 파일/DB 생성 없음을 검사했다.

이는 일반 여러 줄 기능 추가가 아니다. 새 명시적 본문 계약과 원장 migration·처리 분기·원문 승인·완료 소비를 묶어 구현해야 하며 V1 검증만 완화하는 우회는 보류한다. [상세 원인·14개 실행 묶음·전환 완료 조건](SHARED-MEMORY-COMPLETION-REVIEW-2026-09-08.md). 기존 24개 항목과 B0~B8 범위를 유지하며 별도 OSS 서버나 기억 정본을 추가하지 않는다.

## 22. I1-d 구현 — 실제 일반 Enter 입력 순환

21절의 공백을 새 후보/body/request/MCP 계약으로 연결했다. 원문을 치환하지 않고 일반 LF/CRLF/CR/탭을 CAS·인용·자비스 전체 결과 검증에 대응한다. 기존 기억 서버·원장·writer·권한 구조를 재사용하고 별도 OSS 서비스는 추가하지 않았다. 접수 파일/원장 사이 종료 복구와 envelope 전체 digest 결합도 수정했다.

실제 CLI/MCP의 혼합 4개/일반 LF 64개 sensitive record, 두 클라이언트, control completed/dashboard stored=true, 삭제 후 재저장·rollback·컴파일 중 조회를 확인했다. Python 621 passed/2 skipped. 자비스 결합 검사 245 passed/1 timeout 후 동일 실패 검사 단독 1 passed이며 처음부터 전체 통과라고 보고하지 않는다. [V3 인수·새 profile 설정·기존 계약 보존·원장 전환](REMEMBER-V3-ACCEPTANCE-2026-09-08.md).

다음 범위는 실제 정정 UI와 앱별 기억 공급/범위, context pack·전달 이력, 원본 차단 전파, 운영 전환/복원과 검색 품질이다. 네 OSS의 장점만 흡수한다는 방향과 기존 B0~B8 전체 완료 기준은 유지한다.

## 23. 공통 기억 운영 선행 부하 — 2026-09-08

기존 CAPACITY-PLAN의 구조 데이터 규모를 실제 CLI/원장/봉인 검색/백업 복원으로 검증했다. 5,000 원본과 실제 정규화 100,000 units, 인용 page 10,000/conflict 1,000 fixture, 100회 CLI 검색을 확인했다. [인수 보고서](CAPACITY-ACCEPTANCE-2026-09-08.md). 실제 앱별 접근 범위나 문맥 공급 완료로 확대하지 않는다.

보존 조회의 봉인 DB 쓰기 접근을 제거하고 파생 인덱스 batch transaction으로 세대 생성 단일 실측을 59.36→23.78초로 줄였다. FULL durability와 세대 검증을 유지하며 실패 rollback·기존 active 유지·재시도를 검사했다. 검색 p95 약 344ms는 CLI startup을 포함한 합성 한 문구 100회 값이다. 새 graph/벡터 의존성의 근거로 쓰지 않는다.

새로 재현한 unit cap의 파일 수 적용 결함은 I5/P1에 추가했다. 원본/단위 예산과 초과 파일 보존 계약을 먼저 고치며 운영 cap 증대는 보류한다. 100회 managed 쓰기·대용량 동시 조회·실제 압축/공간 성장·한국어 질문 평가는 계속 남는다. 앞서 확정한 앱/범위→공통 context pack·전달 이력→운영 전환 순서를 유지한다.

## 24. 공통 기억 수집 예산 후속 — 2026-09-08

23절의 unit cap 결함을 실제 신규 unit 계수와 별도 원본 시도 수 상한으로 수정했다. 원본의 일부분을 완료 처리하는 별도 저장 상태는 추가하지 않고, 초과 원본 보존·다음 실행 재개와 오류 안내를 기존 CLI/원장/단일 writer에 연결했다. [예산 계약 및 실제 CLI/대용량 인수](INGEST-BUDGET-CONTRACT-2026-09-08.md).

원본·파생 기억·검색 인덱스의 기존 관계와 자비스 요청 V1/V2/V3 계약은 유지한다. 이번 변경으로 앱별 접근 범위·공통 context pack이나 운영 배포까지 완료된 것은 아니다. I5 신규 행 제한 결함은 소스에서 해소됐으며, 앞서 유지한 B4~B8 전체 순서와 보류 조건은 계속 적용한다.

## 25. 실제 두 client의 공통 기억 인수 — 2026-09-08

[Codex/Claude 실제 CLI 인수](AGENT-CLIENT-MEMORY-ACCEPTANCE-2026-09-08.md)로 SDK 두 프로세스의 간접 증거를 보강했다. 실제 도구 6건과 양방향 검색·원문·generation/record version을 대응했다. 명시적 배치와 결정적 compile fixture를 사용했으며 실제 요약 품질·자동 로그 수집/문맥 주입과 구분한다.

첫 Codex 호출은 승인 설정으로 실패했는데 process exit는 0이었다. native tool status/result 검사로 이를 실패 처리하고, 해당 격리 MCP 도구만 허용한 설정으로 실제 인수를 완료했다. 일반 stdio의 sb_run 오안내도 수정했다. [범위 ADR](SHARED-MEMORY-SCOPE-ADR-2026-09-08.md)에 기존 단일 owner fence와 project 분류 결손, 자비스 발급/SB 소비, 정정·삭제·복원·context 경계를 남겼다. 일반 검색 필터를 프로젝트 권한으로 승격하거나 새 SB 승인 엔진을 만드는 방식은 보류한다.

## 26. 실제 반복 쓰기 선행 검사에서 발견한 회수/갱신 결함

[브리핑 예산과 세대 갱신 수정](BRIEFING-RECORD-BUDGET-2026-09-08.md): 과대 브리핑의 MCP 읽기 실패와 `.sb/compiled` 미승계로 자동 갱신이 제안으로 잘못 분류되는 문제를 재현·수정했다. 실제 3회 저장/배치/동시 조회 및 구버전 자료 갱신·백업 복원을 확인했다. 선택적 문맥과 실제 결과 증거를 강화하되, 이 브리핑 분량 제한을 B5 공통 context pack·전달 receipt 완료로 간주하지 않는다. 계획 규모의 100회 쓰기는 새 인수 도구의 full 실행으로 확인하며 앞선 범위·주입·운영·검색 품질 순서의 잔여 조건을 유지한다.

## 27. 계획 규모의 실제 배치에서 충돌 후보 계산 개선

[대용량 후보 계산 수정](CONFLICT-CANDIDATE-CAPACITY-2026-09-08.md): 전체 corpus를 매 unit마다 다시 세던 작업을 실행 내 빈도·역색인·상위 후보 재사용으로 바꿨다. 점수와 반환 순서는 독립 기준과 400개 사례에서 대조했다. 새 graph/벡터 서버나 별도 기억 DB를 추가하지 않았다. 10만 단위 프로파일과 중단 후 실제 배치/MCP 회수는 완료했으나, 100회 반복과 전역 상위 후보의 새 기억 검토 충분성·한국어 품질·운영 지연은 남는다.

## 28. 검색의 부족을 실측한 뒤 선택적 개선

[합성 한국어 질문 100개 기준선](KOREAN-SEARCH-BASELINE-2026-09-08.md)을 CLI와 실제 MCP로 측정했다. 전체 문구 MATCH와 MCP의 연속 문자열 재검사 때문에 어순 변경·자연어·의역 50개가 미회수였다. 정답 있는 90개 중 상위 5개 회수는 40개이며, 근거 record/출처·세대 대조는 통과했다. 평가용 synthetic 자료를 실제 사용자 질문 인수로 취급하지 않는다.

LightRAG의 평가·근거 연결 개념을 기존 검색에 적용할 구체적 근거가 생겼다. 먼저 봉인/비봉인/레코드 선택의 질의 의미를 일치시키고 같은 입력의 회수율과 잘못된 주제 회수를 비교한다. 하이브리드·관계 확장은 삭제/복원/출처/범위가 결합된 경우에만 후속 평가한다. 공통 기억 정본, 자비스 실행 책임, dev-wiki 원문, 별도 서버/Proxy를 추가하지 않는 경계는 유지한다.

## 29. 기존 검색의 어순 처리와 근거 일치 구현

[공통 질의 개선](KOREAN-QUERY-CONSISTENCY-2026-09-08.md)은 별도 OSS 서비스나 인덱스를 추가하지 않고 기존 trigram·봉인 세대·MCP record 검사를 연결한다. 합성 질문의 어순 변경 20개를 회수했고 연속 문구 우선·같은 record의 모든 검색어·최종 limit을 검사했다. 자연어와 의역, 실제 사용자 질문, context pack/실제 전달과 범위·삭제 결합은 여전히 필요하다. 100회 쓰기 검증의 제품 고정을 위해 별도 worktree에서 개발하며 인수 종료 후 병합한다.

## 30. 공통 기억 수명주기의 중단 사본 정리

[미봉인 사본 복구](STAGING-RECOVERY-2026-09-08.md)는 실제 강제 종료 뒤 다른 배치가 성공해도 raw 사본이 남던 문제를 수정한다. 기존 writer 잠금과 유지보수에 연결하며 별도 서버·원장·승인 구조를 추가하지 않았다. 구버전 잔여 1개를 재현하고 수정 후 잔여 0개·원문 보존·두 기억의 실제 MCP 회수를 검증했다. 자비스의 기존 문맥/근거 저장을 재사용할 경계도 대조했다. B5 세션 실제 전달·범위/삭제 결합과 운영 전체 인수는 계속 필요하다.

## 31. 기본 검색 확장의 정확 문구 제어

[큰따옴표 문구와 질의 예산](SEARCH-PHRASE-ACCEPTANCE-2026-09-08.md)을 기존 공통 parser에 추가했다. 새 서비스/인덱스 없이 연속 문구·경로 보존·잘못된 입력 오류를 검증했고 기존 100질문의 회수 지표를 유지했다. 자연어 의미 검색과 B5의 실제 모델 문맥 전달을 이 기능으로 대체하지 않는다. 기존 정본/자비스/개발 문서 경계와 전체 남은 범위는 유지한다.


## 32. 인계 보강 — 기존 조립기와 공통 기억 공급의 차이

[공통 문맥 공급 분석](CONTEXT-DELIVERY-GAP-ANALYSIS-2026-09-08.md)으로 네 OSS의 장점을 기존 코드에 다시 대응했다. 자비스 context snapshot은 근거 메타데이터이며 실제 본문 전달 receipt가 아니다. provider의 untrusted, 여러 줄 원문, live 관측 조건과 총량 계산을 격리 실행으로 확인하고 C1~C8의 코드 경계·우선순위·완료 기준을 추가했다.

code-brain의 작은 context pack과 memory-bank의 세션 중복 억제는 자비스 기존 context/projection 및 실제 agent 전송 경계에 연결한다. Tencent의 공유 범위는 검증된 원본 분류와 함께 확장하며, LightRAG의 검색 개선은 기존 질문 평가를 통과한 기능만 채택한다. 별도 기억 서버·Proxy·원문 DB와 전역 훅은 도입하지 않았다. 이번 산출물은 재현 도구와 구현 세부 계획이며 공통 문맥 공급·운영 인수 완료를 의미하지 않는다.


## 33. 선택적 문맥의 본문 준비 구현

자비스 `3360fe7`의 [reference-only 본문 묶음](MEMORY-REFERENCE-PREPARATION-2026-09-08.md)은 code-brain의 작은 문맥·예산 개념을 기존 read adapter와 연결한다. source/citation/record/세대와 원문을 보존하며 Tencent식 별도 기억 서버나 memory-bank 전용 수집 훅을 설치하지 않았다. 동일 ID의 출처 불일치는 독립 리뷰로 발견해 수정했다.

관련 회귀와 실제 SB MCP→adapter→JSON 준비는 검증했다. 실제 모델 전달과 session/compaction receipt, 삭제/정책/프로젝트 범위 연결은 후속 구현이며 전체 목표의 완료 조건을 유지한다. 외부 코드를 복사하거나 신규 OSS 의존성을 추가하지 않았다.


## 34. 공통 기억의 명시적 조회·차단 정책 연결

자비스 `63bdd02`의 [CLI 참고 기억 경로](MEMORY-REFERENCE-READ-2026-09-08.md)는 작은 context pack을
기존 owner 읽기·차단·세대 수명과 연결한다. source/record/digest를 보존하고 출력 전체 예산을
계수한다. 동시 정책 교체와 만료, 오류 정리를 보강했으며 실제 CLI/MCP와 77개 회귀를 검증했다.

별도 공통 기억 서버·원문 저장소·Proxy나 OSS 코드를 추가하지 않았다. 명시 CLI 조회는 실제 모델
전달 receipt를 대체하지 않는다. memory-bank식 session 중복과 삭제 수명, Tencent식 검증된 공유
범위, LightRAG식 품질 개선은 각각 기존 C6/C7/C8 및 질문 평가의 완료 조건을 통과해야 한다.
운영 배포·100회 쓰기 인수·대기 검색/복구 병합과 기존 B4~B8 전체 범위는 유지한다.


## 35. 작은 context pack의 실제 모델 소비 확인

[실제 모델 인수](MEMORY-REFERENCE-MODEL-ACCEPTANCE-2026-09-08.md)로 SB→자비스 CLI→제한된
reference JSON→native Codex 답변을 검증했다. 원문에만 있는 무작위 값과 정확한 출처·세대를
회수했고 빈 결과 대조를 통과했다. 별도 OSS 서버/Proxy나 모델별 기억 정본은 만들지 않았다.

code-brain식 예산 있는 문맥의 소비 증거를 추가한 것이며 memory-bank식 session 중복/compaction,
삭제 계보와 Tencent식 검증 범위의 완성을 대체하지 않는다. 기존 작업 실행기의 승인 입력·비영속
세션을 확인했으므로 제품 자동 주입은 해당 계약을 연결하기 전까지 보류한다.


## 36. LightRAG 흡수 선행 — 기존 벡터 검색의 필터 일치

[기존 hybrid 수정](HYBRID-FILTERS-2026-09-08.md)은 새 검색 서버를 추가하지 않고 현재 sqlite-vec와
committed search DB를 연결한다. cosine 전용 후보의 출처/지식 상태와 필터를 복원하고 정정 전
본문을 제외했다. 실제 CLI와 전체 회귀로 검증했으며 새로운 OSS 코드/의존성은 추가하지 않았다.

운영 hybrid는 아직 보류한다. 봉인 세대·삭제/복원·모델 identity 수명과 실제 한국어 품질/성능의
완료 조건을 적용한 뒤 활성화 여부를 결정한다. 기존 자비스 승인·참고 기억·session 전달 경계와
정본 역할을 유지한다.


## 37. LightRAG 흡수 선행 — 기존 벡터 재생성의 실패 보존

[벡터 재생성 수정](VECTOR-REBUILD-ATOMICITY-2026-09-08.md)은 기존 sqlite-vec 경로를 보완했다.
새 OSS 코드·의존성 없이 모델 실패가 이전 검색 DB를 없애는 결함과 대량 SQL 인자 한계를 수정했다.
동시 reader·CLI·강제 종료·전체 회귀로 검증했고, 제품 `5d25d3a`를 기존 네 커밋 뒤에 병합한다.

봉인 generation의 vector는 현재 enabled=0/rows=0 계약이다. manifest와 같은 reader pin,
모델 identity, 삭제/정정/복원 수명이 연결되기 전에는 hybrid를 운영 활성화하지 않는다.
대규모 임베딩 메모리와 실제 질문 품질, 강제 종료 임시 DB 회수는 별도 완료 조건으로 유지한다.
자비스와 SB의 기존 정본·승인·session 전달 경계를 유지하며 별도 기억 서버는 추가하지 않았다.


## 38. 기존 기반의 대규모 인수·병합·읽기 무결성

[100회 쓰기와 동시 회수/복원](WRITE-CYCLE-ACCEPTANCE-2026-09-08.md)을 통과하여 기존 대기
검색/복구 제품 다섯 커밋을 원 작업공간에 반영했다. 별도 기억 정본이나 네 OSS의 전체 설치 없이
현재 SB 기반에서 공통 MCP 읽기의 지속성과 신규 기억 회수를 검증했다.

추가 [봉인 무결성 수정](GENERATION-INTEGRITY-2026-09-08.md)은 이미 기록된 manifest와
파일 digest를 읽기 검증에 연결했다. 최신 SB와 검증된 자비스 CLI의 실제 인수도 통과했다.
LightRAG식 의미 검색 활성화와 memory-bank식 session 수명, code-brain식 전달 예산의 실제
session 결합, Tencent식 검증된 범위는 각 남은 완료 조건을 계속 따른다. 높은 쓰기 지연도
측정된 개선 대상으로 유지하며 운영 배포·자동 주입 완료로 계산하지 않는다.


## 39. 기존 기반의 쓰기 성능 개선

[세대 쓰기 프로파일](GENERATION-WRITE-PERFORMANCE-2026-09-08.md)로 복사·작은 동기 쓰기·
제외 디렉터리 순회와 compile 재처리 비용을 분리했다. `fe21016`은 새 OSS/queue/서버 없이
기존 봉인 방식에서 중복 비용을 줄였고, 같은 manifest·전체 회귀·실제 MCP/복원을 검증했다.

단일 프로파일의 기록 12.24초·처리 96.83초는 여전히 개선 대상이다. 별도 파생 원문 cache와
쓰기 응답 계약 우회는 source/version/삭제·세대 계약이 준비되기 전까지 보류한다. 네 OSS의
선별 흡수 방향, 자비스 전달 수명과 범위, 봉인 의미 검색·실제 품질·운영 인수는 그대로 유지한다.


## 40. 기존 기반의 반복 보호 비용 축소

[보호 처리 동등성 최적화](REDACTION-PERFORMANCE-2026-09-08.md)는 기존 source별 정책과
정규화 결과를 유지하면서 불필요한 regex 실행을 줄인다. 새 서버·캐시·모델별 기억 DB 없이
현재 SB의 공통 writer를 개선했다. 같은 합성 대용량 단일 프로파일의 run은 96.83→74.07초이며,
기록 요청 자체는 약 12초로 남는다. 이전 출력 oracle과 실제 두 MCP/복원을 함께 확인했다.

정책 검사 자체를 생략하거나 삭제 수명과 결합하지 않은 원문 캐시를 추가하지 않는다.
이 성능 단위의 진척은 자비스의 session/compaction/삭제·범위 연계, 봉인 의미 검색,
실제 질문·클라이언트·운영 검증을 완료한 것으로 계산하지 않는다.


## 41. 의미 검색 선행 조건 — 파생 DB 재생성 경계

[벡터 경로 보호와 종료 복구](VECTOR-RECOVERY-SAFETY-2026-09-08.md)는 기존 standalone
재생성기의 외부 디렉터리 링크·게시 시 경로 교체·자식 잠금 수명을 보강했다. 새 의미 검색 서버나
별도 기억 정본을 추가하지 않았다. 실제 CLI 종료/재시도·기존 reader 보존·필터/정정을 검증했다.

관측할 수 없는 열린 FD가 있어 이번 호스트의 임시 DB 자동 회수는 보류한다. 이 결과를 삭제
완료로 주장하지 않는다. LightRAG 장점의 실제 흡수 완료에는 봉인 vector 논리/물리 binding,
공통 MCP의 의미 record/citation 선택, 삭제·정정·복원·실제 한국어 품질 검증이 여전히 필요하다.
자비스 세션/compaction/삭제·범위와 운영 인수의 기존 완료 조건도 유지한다.


## 42. LightRAG 장점 흡수 — 기존 봉인 세대 안의 근거 의미 검색

제품 `cbb910d`: [봉인 의미 검색 인수](SEALED-VECTOR-ACCEPTANCE-2026-09-08.md).
기존 SQLite에 인용 레코드별 float32 vector를 저장하고 모델·출처·세대 digest를 결합한다.
새 서버/그래프 DB/Proxy/외부 코드 복사 없이 기존 검색과 MCP schema 4/5의 record 선택을
개선했다. 두 실제 MCP·CLI 정정/삭제·백업 복원에서 같은 원문/세대와 삭제 후 미노출을 확인했다.

합성 모델의 수명주기 인수와 실제 모델의 검색 품질은 구분한다. 운영 hybrid는 기본 false이고
한국어 질문·무정답·대용량 지연은 후속 필수 항목이다. Tencent의 범위 관리, code-brain의
문맥 예산, memory-bank의 세션 중복/compaction은 기존 공통 인터페이스와 자비스 reference를
재사용하되 미완료 전달/삭제·범위 계약을 건너뛰지 않는다. 개발 정본은 dev-wiki/Git로 유지한다.


## 43. 실제 모델 평가와 도입 보류 기준

[BGE-M3 실행 경계·실측](REAL-EMBEDDING-PROCESS-2026-09-08.md)으로 합성 벡터 인수에서
실제 모델 검증으로 진행했다. 기존 pinned 모델을 별도 평가 캐시에 준비했고 로컬 인코딩·
유한 subprocess 실행·fallback 오류를 보강했다. 외부 OSS 소스/서버를 추가하지 않았다.

작은 실제 CLI/MCP 검사에서 자연어·의역의 정답 회수와 동시에 무정답의 후보 노출 및 약 6초
검색 지연이 확인됐다. 기존 100질문 전체 비교는 고정 소스에서 진행 중이다. LightRAG식
검색의 장점을 운영에 채택하려면 실제 사용자 질문과 낮은 관련성·지연 기준을 충족해야 한다.
별도 reranker/그래프/모델 상주 서버를 검증 없이 늘리지 않으며 나머지 세 OSS의 session·
문맥 예산·범위와 기존 자비스 운영 인수의 미완료 조건도 유지한다.


## 44. 검색 품질 실측과 근거 충분성의 구분

[실제 BGE-M3 100질문 비교](SEMANTIC-RELEVANCE-2026-09-08.md)를 끝냈다. 근거 Recall@5는
66.67%→100%지만 무정답은 10/10에서 0/10 빈 결과로 악화됐다. 최신 제품의 명시적 최소
유사도 설정은 낮은 후보를 줄이나 알려진 주제의 없는 세부정보까지 판별하지 못한다.

LightRAG식 근거 검색의 장점은 기존 세대/인용 구조에서 확인했고, 운영 적용에는 자비스의
실제 모델 소비·근거 부족 응답·문맥/삭제 수명과 사용자 평가가 필요하다. threshold를 권한이나
사실 신뢰도로 사용하지 않는다. 추가 모델·서버를 늘리는 대신 기존 재로딩 지연과 agent별
메모리 비용을 먼저 측정·개선하며 나머지 세 OSS의 문맥/세션/범위 과제도 유지한다.


## 45. 공통 기억 기반의 모델 배치 수명 개선과 인계 후속

제품 `701e966`: [실제 배치 출력·수명주기와 다음 우선 목록](EMBEDDING-BATCH-ACCEPTANCE-2026-09-08.md).
기존 SentenceTransformer/봉인 generation을 재사용하고 한 세대에서만 모델 프로세스를 공유한다.
같은 실제 모델 출력과 종료·잠금·정정/삭제·복원 검증을 유지하면서 129개 입력의 단일 비교는
28.75→16.81초였다. 외부 OSS 코드·별도 서버·agent별 DB를 추가하지 않았다.

인계 문서의 현재판을 다시 읽어 세컨드브레인 정본·자비스 실행/검증·dev-wiki 개발 결정의 경계를
유지했다. 제품/API 계약 변경은 없다. LightRAG식 검색 개선의 실제 배치 비용은 줄였지만,
자비스의 실제 세션 전달/삭제 수명과 code-brain·memory-bank의 문맥/중복 이력, Tencent식
원본 범위 분류를 다음 우선 과제로 유지한다. 단일 owner 공유와 SDK MCP 인수를 모든 앱의
자동 수집·주입 또는 프로젝트별 접근 통제의 완료로 계산하지 않는다.


## 46. code-brain·memory-bank 문맥 수명의 실제 소비 경계

[실제 모델 정정·삭제·보관 사본 재전송](REFERENCE-MODEL-LIFECYCLE-2026-09-08.md)을 추가했다.
새 조회는 최신 값/삭제를 반영하지만, 소비자가 보관한 과거 본문을 다시 보내면 과거 값이 다시
사용된다. 공통 기억 provider의 삭제 검사로 세션의 전달/무효화 인수를 대체하지 않는다.

[자비스 전달 수명 계약안](REFERENCE-DELIVERY-LIFECYCLE-CONTRACT-2026-09-08.md)은 기존 reader와
context/projection을 재사용하는 전송 상태·중복·실제 epoch·삭제 경합 조건을 정한다. 이번에는
SB 작업공간의 인수 도구를 확장했고 자비스 제품·새 DB·외부 OSS·운영 설정은 변경하지 않았다.
다음 자비스 측 구현은 해당 소비자 경계에서 수행하며 SB에 별도 승인/전송 상태 엔진을 추가하지 않는다.


## 47. 소비자 제출 경계의 기존 reader 재사용

[자비스 문맥 제출 재검사](REFERENCE-SUBMISSION-ACCEPTANCE-2026-09-08.md)를 기존 reference reader에
연결했다. SB 정본·MCP·세대 계약은 유지하고 자비스 소비자에서 문맥 변조/과거 객체 재전송과
제출 중 삭제의 결과 사용을 검사한다. 실제 모델 인수와 별도 모델 리뷰를 통과했다.

code-brain·memory-bank의 문맥/세션 장점 중 제출 경계만 구현한 단계다. 객체 단위 한 번 시도는
여러 프로세스와 세션 전체의 중복 억제가 아니며 영구 receipt·실제 compaction·삭제 계보가
필요하다. 기존 context/projection을 확장하는 후속과 Tencent식 범위 분류·운영 인수는 유지한다.


## 48. 인계 최종 방향 재대조와 세션 영구 이력

인계 문서 현재판을 다시 읽고 네 OSS 후보를 기존 구현과 대조했다.
[영구 전달 원장·수정/개선/고도화 14항목](REFERENCE-DELIVERY-JOURNAL-ACCEPTANCE-2026-09-08.md)에
분류와 완료 증거를 통합했다. memory-bank식 세션 중복 관리와 code-brain식 문맥 공급은 기존
자비스 reader/AuthorityDb에서 보강했다. SB 정본·MCP wire 계약·dev-wiki 개발 정본 경계는 유지한다.

실제 Node 프로세스 6개와 native 모델 5회에서 영구 이력을 검증했으며 별도 기억 서버/Proxy/
에이전트별 DB/OSS 소스 복사는 없다. 합성 adapter session ID를 실제 native session 연동으로
계산하지 않는다. Tencent식 검증된 사용자/프로젝트 범위와 실제 앱 채택, LightRAG 후보의
검색 근거 충분성·지연·평가, GUI/운영/DR 조건을 후속 필수 작업으로 유지한다.


## 49. memory-bank/code-brain 세션 장점의 실제 native 검증

[실제 UUID 전달과 native 원문 보존](NATIVE-SESSION-ACCEPTANCE-2026-09-08.md)으로 합성 session ID에서
실제 Codex 세션으로 인수를 확장했다. 기존 SB/JARVIS를 재사용했고 native 모델 10회와 원장 차단을
검증했다. 새 실행기/기억서버/Proxy를 제품에 도입한 단계는 아니다.

code-brain/memory-bank식 문맥 관리에는 provider 삭제뿐 아니라 native rollout과 thread_history
SQLite·백업의 보존/폐기가 필요하다는 실측을 추가했다. 설치 CLI의 기본 플러그인 자산 다운로드도
별도 fixture에서 관측해 명시적으로 비활성화했다. 검증용 실행체 사본과 다운로드 관측은 OSS 소스를
제품에 채택했다는 뜻이 아니다. native 제품 연결은 관리형 보존 계약까지 보류하고 기존 범위/운영 목표를 유지한다.
