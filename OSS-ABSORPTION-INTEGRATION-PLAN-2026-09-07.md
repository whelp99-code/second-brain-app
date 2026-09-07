# Second Brain 기반 OSS 장점 흡수 — 통합 분석·구현 계획

기준일: 2026-09-07, 후속 대조: 2026-09-08. 상태: 사용자 확정 방향 병합. R1~R3 및 검색·reader 복구, 자비스 다중 record 소비·R4 시간 처리에 이어 64개 record 저장 결과 검증을 보강했다. 최신 검증은 13절과 구현 원장을 따른다. 전체 인수·운영 배포 완료를 뜻하지 않는다.

인계 원문: [자비스 작업 인계](../Orca-JARVIS/docs/second-brain-oss-absorption-handoff-2026-09-07.md).
기존 결함·개선 정본: [24개 항목 분석](IMPROVEMENT-BACKLOG-2026-09-07.md).

## 1. 병합한 결정과 범위

1. Second Brain을 유일한 개인·업무 기억 정본으로 유지한다. 기존 CAS·원장·세대·MCP·삭제/복원 구조 위에서 개선한다.
2. **1차 범위는 자비스 + Second Brain + 서로 다른 에이전트의 공통 기억 사용이다.** 기존 I7의 다른 업무 프로젝트/실행자 대량 연결은 후속으로 이동한다.
3. LightRAG, TencentDB-Agent-Memory, code-brain, memory-bank에서 필요한 계약·알고리즘·설계만 흡수한다. 기본 방식은 기존 코드 재사용과 설계 반영이며, 코드 복사나 라이브러리 추가는 파일별 필요성을 확인한 뒤 결정한다.
4. 자비스는 작업 제어·결과 검증, Second Brain은 기억, dev-wiki/Git은 개발 규칙·결정의 원문과 이력을 유지한다. 개발 문서 검색 연결은 정본의 대체나 dev-wiki 전체 자동 색인을 뜻하지 않는다.
5. 별도 기억 서버·에이전트별 기억 DB·모델 Proxy·워커 오케스트레이터·전역 훅을 도입하지 않는다. 사용 에이전트마다 얇은 연결부만 둔다.
6. R1 입력 유실, R2 자비스 해석 실패, R3 요청 기억 복원 실패는 여전히 먼저 해결한다. OSS 채택은 이 결함들을 우회하는 방법이 아니다.

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
| 자비스 | transport 실연결, adapter 결함 R2 | request/outbox 구현·fixture 검사, 전체 운영 순환 미완료 | 자비스 사건/결과 계약 담당 | 소비 adapter 경로 보강 필요 | R2 → 실제 한 요청의 저장·상태·재사용 |
| Codex | MCP 표준 서버·설정 예시 재사용 가능 | 일반 inbox 경로 가능, R1 해결 선행 | 전용 JSONL 파서·fixture 있음 | 공통 context pack 연동 신규 | 실제 Codex 클라이언트 설정과 읽기/쓰기 재현 필요 |
| Claude Code | MCP 표준 서버·설정 예시 재사용 가능 | 일반 inbox 경로 가능, R1 해결 선행 | 전용 JSONL 파서·fixture 있음 | 전용 훅 복제 대신 공통 공급 서비스 | 실제 Claude 클라이언트와 Codex 간 교차 회수 필요 |
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
| P0 수정 — 자비스 자동 연결 | 라이브러리·하네스 성공만으로 운영 요청이 저장되지 않음 | I1-a/c/e: 기존 runtime에 outbox·selector 구성·완료 reader를 주입. 기존 주기 실행으로 pending→proved→settled 재확인, 재시작·중복 처리·cleanup 오류 표시 검증 |
| P0 수정 — 승인 rollback 복구 | SQL rollback 뒤 남은 dispatch metadata가 다른 receipt의 재승인을 막을 수 있음 | I1-b: 바깥 transaction 실패 주입, 원문 보존과 metadata 재발행을 검증. 이미 서명된 요청의 내용을 변경하지 않음 |
| P0 수정 — 갱신 중 읽기 | I3의 LLM 실행 중 배타 잠금은 소비자 10초 deadline과 충돌 가능 | 준비와 활성화 잠금 구간을 분리하되 단일 writer·reader pin·삭제 보장을 유지. 느린 갱신 중 조회와 중단 복구를 실측 |
| P1 개선 — 일상 입력과 정정 | 일반 Enter 여러 줄 미지원, V1 owner correct 승인 대상 결합 부족 | 버전이 있는 본문 계약과 기존 V2 target/delegation 정정을 연결. 원문 전체 대응 및 승인 후 대상 변경 거부 검사 |
| P1 개선 — 에이전트 공통 사용 | 두 MCP 프로세스 검증은 실제 다른 앱의 저장·주입 지원 증거가 아님 | 실제 Codex/Claude 등 사용 클라이언트별 읽기·쓰기·수집·주입 지원표, A 저장→B 출처/버전 회수 실사용 검증 |
| P1 개선 — 프로젝트 범위 | sensitivity와 지식 상태 scope만으로 접근 범위를 제한할 수 없음 | 공통 project/user/agent 범위 계약과 버전 호환. 검색·원문·관계 확장 모두 범위 밖 거부 검사 |
| P1 고도화 — 문맥 공급 | 검색 limit만으로 세션 중복·compaction 후 재전달을 관리하지 못함 | B5: 관련도/분량 제한, 근거·버전·선택 이유, 실제 전달 receipt와 중복/재시도. 실패·미확정 실행을 성공 기억으로 승격하지 않음 |
| P1 개선 — 운영 복구와 가시성 | 소스와 release 차이, 과거 generation 잔여물, 백업 복원 신뢰성 | B3/B6: 원장·디렉터리 대조, 독립 복원 검사, readiness·오류·백업 시각 표시. 실행 파일과 provider generation의 함께 전환/복구 검증 |
| P2 고도화 — 한국어 검색 품질 | 외부 프로젝트 README 성능은 현재 시스템 성능 근거가 아님 | B7: 한국어 고정 질문 100~300개, 근거 회수·오래된 결정 노출·지연·분량 평가. 5천 파일/10만 unit/1만 페이지 및 100회 반복 목표 실측 |
| 조건부 고도화 — hybrid | 기존 RRF/벡터 코드의 sealed 읽기 쓰기 부작용·메타데이터 손실 | B8: 읽기 전용·출처/범위 보존부터 수정 후 같은 질문 기준선과 비교. 이점이 확인될 때 활성화 |

검증된 변경은 기능 단위로 커밋하고 운영 반영 여부를 별도 기록한다. 신규 OSS 코드를 복사하지 않았으므로 이번 단위에서 외부 파일 라이선스 고지 추가는 없다. 향후 복사 시에는 인계서 기준의 파일·커밋·라이선스/NOTICE를 기록한다. 계획의 네 제품 비교는 고정 커밋 인계 자료이며 최신 upstream 재조사·실측을 의미하지 않는다.
