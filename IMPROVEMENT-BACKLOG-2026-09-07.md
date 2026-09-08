# Second Brain 수정·개선·고도화 분석

최초 분석일: 2026-09-07. 인계 재대조: 2026-09-08, Second Brain `ee4fc13`, 자비스 HEAD `e61893e` 및 현재 기억 모듈. 운영 릴리스 `41f0751aca8906d612961e704bc60dd0855fdabd`는 최초 분석 당시 관측값이며 이번에 운영 실행 버전을 재확인한 값은 아니다.

**현재 판정: 수정된 소스의 자비스 저장→완료 확인→재조회는 격리 실제 MCP에서 동작한다. 운영 중앙 기억 저장소의 전체 완성은 미완료다.** 최초 분석에서 재현한 입력 보존·자비스 해석·요청 기억 복원 결함은 후속 소스에서 수정·검증됐다. 아래 수정 전 원인과 재현은 이력으로 보존한다. 후속 후보 검토·저장 준비 UI와 진행 API는 구현·검증됐다. 현재 미완료 범위는 실제 업무 후보 수집, 앱별 공유·수집·주입, 접근 범위, 운영 전환·복구 및 검색/부하 인수다.

최초 작성은 분석과 목록 작성이었으며 이후 R1~R4, R5/R7/R9, reader 복구와 자비스 순환을 수정·검증했다. 운영 배포와 소스 완료는 구분한다. 쓰기·유실·복원 재현은 독립된 임시 저장소에서 수행했다. 이전 운영 MCP 진단은 읽기 요청이었다. 아래 재현 결과가 운영 데이터의 기존 유실을 입증하는 것은 아니다.

우선순위: P0는 중앙 기억 쓰기 확대 전에 반드시 해결, P1은 안정 운영 완료 조건, P2는 품질·사용성 확장이다. 근거는 **재현**, **코드 확인**, **검증 공백**, **제안**으로 구분한다. 시간·성능 목표는 달성 실적이 아니라 제안된 완료 기준이다.

직전 후속: [후보 CLI 접수 보고서](MEMORY-CANDIDATE-INTAKE-2026-09-08.md). 실제 시각의 원문/DB 불일치와 미커밋 원문 재시도 결함을 수정하고 제품 파일 접수에서 실제 저장 순환까지 검증했다. 실제 task 결과 수집과 approved/no_data 본문 인계는 별도 미완료다.

최신 I1 상태: CLI/dashboard 후보 접수·검토·저장 진행에 이어 **V2 정정의 production saga/control 완료와 중단 복구를 격리 실제 MCP에서 검증했다.** 정정 4개 record를 두 소비자가 회수했고, 최종 완료 저장 실패 뒤 승인 시간이 지나도 재전송 없이 완료됐다. [정정 완료 연결 보고서](CORRECTION-CONTROL-COMPLETION-2026-09-08.md). 실제 task 수집·private 후보/정정 UI·V1 일반 LF·앱별 공유/주입·접근 범위와 운영 배포는 남는다. 아래 과거 분석과 각 후속 기록의 시점을 구분하며 [구현 원장](IMPLEMENTATION-STATUS.md)을 최신 판정으로 삼는다.


> **인계 방향 병합:** [OSS 장점 흡수 통합 분석·구현 계획](OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md)을 추가했다. Second Brain을 유지하며 자비스와 여러 에이전트의 공통 기억을 1차 범위로 한다. 다른 업무 실행자 연결은 후속으로 이동하고, G3 문맥 공급·세션 중복 방지를 공통 기억 단계로 앞당긴다. 아래 24개 ID와 결함 증거는 유지한다.

## 1. 수정 — 10개

### R1. 미처리 inbox 기록 유실 — P0 / 재현 → 소스 수정·검증 완료, 운영 미배포 / Second Brain

- 근거: [generation_runtime.py](sb/generation_runtime.py#L204). INBOX 이외의 세대 변경이 끝나면 staging의 inbox 전체를 삭제한다. 수집 성공 여부·처리 개수와 관계없이 적용된다.
- 재현 A: 기록 2건 저장 → 실제 CLI retry와 같은 EFFECT 경로에서 `retry_failed` 호출 → 재시도 수 0, inbox 0, source_item 0, unit 0.
- 재현 B: 기록 2건 저장 → `run_ingest(limit=1)` → 상태 capped, 수집된 source_item/unit 각각 1, inbox 0. 나머지 1건의 미수집 기록이 보존되지 않는다.
- 영향: retry·compile·brief·정리 등 다른 작업이 새 기억의 수집 전 입력을 지울 수 있다. 처리량 제한이 데이터 유실로 바뀐다.
- 수정: 성공적으로 수집한 항목만 처리 완료로 전이하고 미처리·실패·보류 항목은 후속 세대에 보존한다. 기록 단위의 durable ingress 상태를 기준으로 정리한다. 별도 서버 큐나 watcher 도입 없이 기존 원장·inbox 구조에서 해결한다.
- 완료 기준: 모든 세대 변경 명령을 미처리 inbox와 조합해 검증한다. `limit=1`, source 미선택, LLM 실패, parser 실패, 재시작을 거쳐도 접수한 각 입력이 pending·처리 완료·명시적 거부 중 하나로 설명되어야 한다. 설명되지 않는 유실 0건.

### R2. 실제 자비스 read adapter가 생성 페이지를 거부 — P0 / 양쪽 소스 수정·실제 읽기 검증, 운영 미전환 / 양쪽 리포

- 근거: [mcp.py](sb/mcp.py#L502), 자비스 `src/second-brain-evidence-parser.ts:22,70`.
- 실제 운영 MCP의 `운영 복구` 검색은 data/1건을 반환하지만 자비스 `createSecondBrainReadAdapter(... contract_profile: schema4)`는 `SECOND_BRAIN_PAGE_MALFORMED`를 반환했다. `업무`도 transport는 결과를 반환하지만 adapter는 동일하게 거부했다.
- 원인: 생성 페이지 frontmatter에 `derivation_key`가 포함되지만 자비스는 정확한 허용 키 집합을 검사하며 이 필드를 허용하지 않는다. 통신 계약 검사만으로 드러나지 않는 producer/consumer 불일치다.
- 수정: 저장용 frontmatter와 외부 읽기 응답을 분리하여 명시적인 API 투영을 제공하거나, 두 리포가 합의한 버전에서 계약을 확장한다. 원장 재구축에 쓰는 derivation_key를 원본에서 무조건 삭제하거나 검증기를 느슨하게 풀면 안 된다.
- 완료 기준: 실제 compile 산출물을 실제 자비스 adapter와 상위 소비 경로까지 통과시킨다. 합성 계약 fixture뿐 아니라 raw → compile → MCP → adapter → evidence 검증을 릴리스 게이트에 포함한다.

### R3. 자비스 요청으로 저장한 기억의 백업 복원 실패 — P0 / 소스 수정·회귀 검증, 운영 미배포 / Second Brain

- 근거: [request_executor.py](sb/request_executor.py#L282), [pipeline.py](sb/pipeline.py#L979), [ops.py](sb/ops.py#L343).
- 재현: 기존 서명 fixture 요청을 정상 executor로 처리하면 proved가 된다. 백업 파일도 생성된다. 그러나 복원은 `restored vault citation audit failed`로 실패한다.
- 원인: request executor는 sources가 비어 있는 페이지에 16자리 `memory-candidate` 인용을 기록한다. 기존 복원 검사는 sources의 64자리 CAS hash로부터 만든 인용을 요구한다. 두 경로의 출처 모델이 다르다.
- 수정: provider-owned 기억과 외부 CAS 자료의 출처 계약을 정렬한다. 요청 원장과 결합된 인용을 검증 가능하게 보존하거나 CAS 및 출처를 정상적으로 생성한다. Vault 단일 writer 경계를 지키는 저장 API로 통합한다. 인용 검증을 끄는 방식으로 통과시키지 않는다.
- 완료 기준: remember·correct·forget·export를 포함한 요청 처리 후 backup → 새 경로 restore → 원장·인용·검색·삭제 상태 검증이 성공한다.

### R4. 장기기억 유효기간이 일괄 하루 — P1 / 양쪽 소스 수정·시간 경계 검증, 운영 미전환 / 양쪽 리포

- 근거: [memory_records.py](sb/memory_records.py#L95), 자비스 `src/second-brain-evidence-parser.ts:150`.
- 모든 record의 valid_until을 updated 날짜의 UTC 자정 + 1일로 만든다. 자비스는 현재 시각이 valid_until 이상이면 identity invalid로 거부한다. 실제 저장 시각 기준 24시간도 아니다.
- R2의 추가 필드만 메모리상 응답에서 제거한 진단 실험에서, 검사 시계를 다음 날로 옮기면 `SECOND_BRAIN_RECORD_IDENTITY_INVALID`가 발생했다. 운영 응답·코드는 변경하지 않았다.
- 수정: 사실 자체의 유효기간, 관측 시각, 재검토 필요 시각, 응답 캐시 만료를 분리한다. 프로필·선호·의사결정·일시 상태에 서로 다른 정책을 적용한다. 생성 시각을 매번 갱신하여 오래된 사실을 새 사실처럼 만들지 않는다.
- 완료 기준: 다음 날·30일 뒤에도 보존 대상 기억을 회수하고, 기간이 끝난 일시 상태는 stale 또는 expired로 명확히 구분한다. digest·정정·삭제 계약도 함께 검증한다.

### R5. sealed 검색의 필터 의미 불일치 — P1 / 소스 수정·검증 완료, 운영 미배포 / Second Brain

- 근거: [search.py](sb/search.py#L210).
- `업무` reference 검색 9건; 존재할 수 없는 status로 필터해도 9건; `updated_from=2099-01-01`로 해도 9건; active scope는 항상 0건이었다.
- status·날짜 필터가 sealed 분기에서 적용되지 않는다. active/candidate는 실제 정책 데이터와 무관하게 빈 결과를 돌려준다.
- 수정: 가변·sealed 검색에 동일한 필터 의미를 제공한다. 승인/지식 상태의 정본을 읽기용 투영으로 결합하고, 지원하지 않는 옵션은 명시적인 오류로 반환한다. UNKNOWN을 임의로 APPROVED로 바꾸지 않는다.
- 완료 기준: 날짜·상태·kind·scope의 조합을 두 저장 모드에서 검증한다. 미래 날짜나 존재하지 않는 status는 0건 또는 명확한 지원 불가 응답이어야 한다.

### R6. 중단된 reader와 불완전한 세대 정리 복구 — P1 / reader·현재 전환 복구 수정, 과거 잔여물 미완료 / Second Brain

- 근거: [request_store.py](sb/request_store.py#L969), [generations.py](sb/generations.py#L1028).
- reader lease를 finally에서 지우지만 프로세스 강제 종료는 finally를 실행하지 않는다. readers()는 테이블을 그대로 반환하며 프로세스 생존 여부를 확인하지 않는다. 남은 lease/FD는 이전 세대 정리를 막는다. 활성 포인터 전환 뒤 정리 실패도 가능하다.
- 수정: PID 재사용을 고려하는 프로세스 식별과 lease 복구 절차, 활성화 단계 재개, 격리된 미완료 세대 점검을 제공한다. 살아 있는 reader가 참조하는 자료를 시간 초과만으로 삭제하지 않는다.
- 완료 기준: reader 강제 종료, 포인터 전환 직후 종료, 정리 중 종료에서 중복 없이 수렴한다. CLI에는 실패·접수·활성화·정리 대기 상태가 구분되어야 한다.

### R7. 검색 후처리 전에 limit 적용 — P1 / 소스 수정·검증 완료, 운영 미배포 / Second Brain

- 근거: [search.py](sb/search.py#L213), [mcp.py](sb/mcp.py#L481).
- section 검색에 먼저 limit를 걸고, 그 뒤 kind·record 본문 일치·중복 제거를 적용한다. 제목에만 일치하거나 한 페이지의 여러 section이 상위를 차지하면 실제로 적합한 뒤쪽 기록을 읽기 전에 탐색이 끝난다.
- 수정: record 단위 인덱스 또는 제한된 후속 페이지 탐색을 사용한다. 최종 필터·중복 제거 이후의 결과 개수가 limit 기준이 되어야 한다.
- 완료 기준: 앞 N개가 제외되거나 중복이어도 뒤의 유효 결과를 찾는다. 과도한 전체 스캔을 피할 수 있는 상한과 continuation 규칙을 둔다.

### R8. readiness의 잘못된 정상 판정과 오류 처리 — P1 / 소스 수정·CLI/HTTP 검증, 운영 인수 미완료 / Second Brain

- 근거: [readiness.py](sb/readiness.py#L29).
- 마지막 실행의 성공 여부만 보고 경과 시간을 검사하지 않는다. 백업은 최근 tar.gz의 mtime만 보며 체크섬 검증 여부를 확인하지 않는다. 요청 상태 수는 출력하지만 장시간 pending·failed 여부를 정상 판정에 반영하지 않는다. 요청 DB와 백업 디렉터리 조회의 일부 예외는 정상적인 degraded 응답으로 변환되지 않는다.
- 수정: 마지막 성공 경과 시간, 최근 검증된 백업 receipt, 가장 오래된 pending, adapter 통과 결과, 세대 정리 상태를 포함한다. 비싼 검사는 별도 실행하고 결과를 읽는다.
- 완료 기준: 오래된 성공, 손상된 새 백업, 오래 멈춘 요청, 손상된 journal을 각각 의도된 degraded 상태와 원인 코드로 반환한다.

### R9. 읽기 명령 전체의 세대 고정 보장 — P1 / 소스 수정·검증 완료, 운영 미배포 / Second Brain

- 근거: [cli.py](sb/cli.py#L214), [cli.py](sb/cli.py#L249), [runtime_access.py](sb/runtime_access.py#L21).
- 웹/MCP와 달리 CLI status·search 등의 읽기는 공통 read_root/pin 경로를 일관되게 사용하지 않는다. 경로 resolve만으로는 조회 중 이전 세대 삭제나 여러 시점의 혼합을 막을 수 없다.
- 수정: 읽기 명령 모두를 같은 snapshot context로 연결하고 관련 Config도 고정된 root를 사용하도록 한다. pin을 보유한 채 다시 쓰기 잠금을 요청하는 교착은 피한다.
- 완료 기준: 반복적인 세대 교체와 CLI 읽기를 동시에 수행해 한 응답은 한 세대의 자료만 포함하며, 파일 소멸 오류·혼합 HEAD가 없어야 한다.

### R10. sealed 모드에서 hybrid 설정 무시 — P2 / 코드 확인 / Second Brain

- 근거: [search.py](sb/search.py#L210). sealed 분기는 조기 반환하므로 이후 `_hybrid_or_lexical`에 도달하지 않는다.
- 수정: 실제 지원할 경우 세대에 결합된 vector 인덱스와 검색을 연결한다. 지원 전에는 설정 상태를 명확히 표시하거나 지원 불가로 처리한다.
- 완료 기준: hybrid=true/false가 정의된 실행 경로를 선택하고 벡터 미설치·손상 시 동작이 명시되어야 한다. 단순히 결과 수가 같다는 이유로 동작 여부를 판단하지 않는다.

## 2. 개선 — 8개

| ID / 우선순위 | 개선 내용과 현재 공백 | 구현 방향 | 완료 기준 |
|---|---|---|---|
| I1 / P1 | 자비스 전체 기억 순환 검증. 이전 테스트는 transport·fixture·개별 saga 증거이며 실제 업무 소비까지는 부족하다. | JARVIS 완료 사건 → candidate → outbox → provider → settled → read adapter → 재사용을 연결한 시나리오를 마련한다. 기존 권한 구조를 사용한다. | 유효 기록 1건이 끝까지 연결되고 중복·timeout·재시작에서도 원인과 최종 상태가 추적됨. |
| I2 / P1 | 파일 복원과 서버 재가동을 포함한 재해 복구는 다르다. | 키·설정·provider identity·원장·tombstone·활성 포인터를 묶은 새 호스트 복구 절차를 자동 검증한다. | 새 디렉터리뿐 아니라 깨끗한 런타임에서 읽기·쓰기 재개. 삭제한 기억의 부활 0건. 실제 RPO/RTO 기록. |
| I3 / P1 | 갱신 중 읽기 차단 소스 수정·격리 실측 완료, 운영 부하 인수 남음. | writer mutex와 generation SH/EX 분리, 조회 유지보수 nonblocking, pin·삭제 재검증. [상세 검증](GENERATION-READ-CONCURRENCY-2026-09-08.md). | 격리 실제 자비스 완료 확인·두 클라이언트 조회 약 1.38초. 대표 데이터 p95 2초·timeout 0 목표는 별도 측정. |
| I4 / P1 | 배포 준비 이후 설정·symlink·systemd 활성화는 수작업이며 코드/설정 조합의 회귀 위험이 있다. | 검증된 wheel·잠금 의존성·비밀이 아닌 설정 템플릿·서비스 자산·contract digest·검증 결과를 release manifest로 묶는다. prepare/verify/activate/rollback을 구분한다. | 다른 호스트에서 재현 설치. 중간 실패 때 이전 실행 환경 복구. dirty 소스를 커밋 릴리스로 표기하지 않음. |
| I5 / P1 | 부하·증가량·반복 운영 근거가 부족하다. 세대 변경 시 원본을 다시 복사하고 백업도 큰 잠금을 유지한다. | CAPACITY-PLAN의 5천 파일·10만 unit·1만 page·100회 실행을 실제 managed generation 경로에서 측정한다. 이후 증분 처리·복사량·백업 잠금을 최적화한다. | 데이터 보존·정합성·검색 지연·디스크 증가·복원 시간 보고. 단순 hardlink는 현재 nlink=1·삭제 계약과 충돌하므로 금지. |
| I6 / P1 | 지표는 존재하나 처리 정체·오류·용량을 운영자가 즉시 판단하기 어렵다. | 접수→수집→편집→회수 지연, oldest pending, 현재 실패와 과거 실패, 검증된 백업 나이·가용 공간을 분리한다. 백업 보존기간과 외부 사본 정책을 명시한다. | 실패 원인과 재처리 대상을 한 화면/명령에서 파악. 중요 상태 변화만 알림. 복원 증거 없는 오래된 백업을 임의로 삭제하지 않음. |
| I7 / P1 | 여러 프로젝트를 연결하는 데이터 계약과 실제 수집 범위가 다르다. | 프로젝트별 producer ID, source URI, 원본 사건 ID, content hash, 민감도, 허용 정책, 저장 목적을 합의한다. 자비스가 완료 결과를 라우팅하고 Second Brain은 저장·검색을 담당한다. | 프로젝트 하나씩 연결해 누락·중복·정정·삭제·재전송 검증. Unified DB는 읽기 전용 유지. 모든 원시 터미널 로그를 무조건 저장하지 않음. |
| I8 / P2 | 문서·테스트·모듈 책임이 현재 구조와 어긋난다. 계획서는 0.1.0, 초기 통합 계획은 transport 미구현 상태를 설명한다. | 현재 정본 문서·폐기된 계획·검증된 기준선을 표시한다. 큰 MCP/pipeline 모듈은 프로필/읽기/쓰기 책임으로 나눈다. 타입 경고와 실제 installer 자산 검사도 정리한다. | 현재 설치 경로로 신규 개발자가 동작을 재현. 모든 회귀 게이트가 실패 exit를 전달. 경고를 일괄 억제하지 않음. |

## 3. 고도화 — 6개

아래는 결함 수정 후 추진하는 제안이다. 존재하지 않는 기능을 이미 있다고 간주하지 않는다.

| ID / 우선순위 | 기능 | 사용자 가치·구현 방향 | 완료 기준 |
|---|---|---|---|
| G1 / P2 | 기억 유형과 수명 정책 | 선호·프로필·업무 사실·결정·교훈·임시 상태를 구분한다. 유형마다 유효기간·재검토·민감도·정정 방법을 정의한다. | 오래 보존할 사실이 자동 만료되지 않고, 임시 사실은 최신 상태와 섞이지 않음. R4의 시간 의미 확정 후 진행. |
| G2 / P2 | 한국어 회수 품질 개선 | 짧은 검색, 띄어쓰기·동의어·약어·프로젝트 별칭을 평가한다. 정확 검색을 기준으로 유지하면서 선택적 semantic retrieval/reranking을 추가한다. | 실제 질문 100~300개로 Recall@k·정답 출처 포함률·오답 포함률·지연 측정. 평가셋에 없는 성공 수치를 주장하지 않음. |
| G3 / P1 | 작업 시작용 기억 묶음 | 인계에 따라 공통 기억 1차 범위로 상향. 자비스가 작업·프로젝트·기간·토큰 예산을 전달하면 관련 기억, 근거, 미해결 충돌, 최신성 정보를 돌려준다. | 사용 예산 내 제공, 실제 전달 receipt·세션 중복·compaction 후 재공급 검증. 출처 없는 사실 추가 0건, 주입된 지시문을 실행 권한으로 사용하지 않음. |
| G4 / P2 | 시간에 따른 사실·정정 관계 | ‘예전에는 A, 현재는 B’와 실제 모순을 구분한다. 유효 시점·관측 시점·대체 관계를 모델링한다. | 특정 날짜 기준 조회, 변경 사유 추적, 정정/삭제 후 오래된 값이 현재 사실로 재노출되지 않음. |
| G5 / P2 | 기억 처리 상태와 근거 UI | 접수됨·처리 중·보류·실패·검색 가능을 보여주고 원본/인용/정정 이력을 연결한다. | 사용자가 기록 1건의 현재 상태와 다음 행동을 설명 없이 파악. macOS 기능은 실제 지원 플랫폼에서 별도 E2E 검증. |
| G6 / P2 | 검증된 업무 결과의 재사용 | 자비스가 검증한 업무 완료·해결책·반복 교훈을 저장 후보로 만들고, 다음 유사 업무에 관련 기억을 제시한다. | 완료 사실→저장 근거→재사용 결과 연결. 검증되지 않은 에이전트 요약의 자동 사실 승격이나 실행 권한 부여 없음. |

## 4. 진행 순서와 완성 판정

1. **R1 → R2 → R3:** 입력 보존, 자비스 실제 해석, 복구 가능성부터 통과시킨다. 세 항목이 해결되기 전에는 여러 프로젝트의 주요 기록을 대량 유입시키지 않는다.
2. **R4~R9 + I1~I3:** 시간·필터·장애 복구·실제 기억 순환·읽기 가용성을 확정한다.
3. **I4~I8:** 재현 배포·부하·운영 지표·프로젝트별 연결을 완성한다. 기존 계획의 100회 연속 실행 게이트를 실제로 채운다.
4. **R10 + G1~G6:** 유형·검색 품질·작업 맥락·사용자 경험을 확장한다. 벡터 검색은 선택 기능을 유지한다.

중앙 기억 저장소 완료 조건은 테스트 총개수가 아니라 다음 불변 조건이다: 접수한 기억이 사라지지 않음; 자비스가 형식/시간 오류 없이 읽음; 중복 전송과 재시작에 수렴함; 정정·삭제·복원 후 의미가 유지됨; 여러 프로젝트의 출처가 분리됨; 갱신 중 필요한 시간 내 회수됨; 새 호스트에서 복구 후 같은 동작을 재현함.

## 5. 역할 경계

채택된 dev-wiki ADR에 따라 자비스는 제어·실행 판단, Second Brain은 개인·업무 기억, dev-wiki는 개발 결정·리포 간 규칙의 정본이다. 여러 프로젝트의 공통 기억 접근점을 만들더라도 이 정본을 중복시키지 않는다. 개발 관련 요청은 자비스가 dev-wiki와 Second Brain의 필요한 자료를 각각 조회하여 근거를 모으는 방향이 적절하다.

새 실행 authority, 기본 경로 승인 장벽, server watcher/queue/event bus, Unified DB 쓰기, vault remote를 이번 고도화의 전제로 추가하지 않는다.

## 6. 재현 증거 요약

| 점검 | 결과 | 성격 |
|---|---|---|
| pending 2건 뒤 retry | pending 0, source_item 0, unit 0 | 임시 저장소 실재현 |
| pending 2건, ingest limit 1 | capped, source_item 1, pending 0 | 임시 저장소 실재현 |
| 운영 기록 검색: transport → adapter | data/1건 → invalid/PAGE_MALFORMED | 실제 운영 읽기 + 자비스 코드 |
| 업무 검색: transport → adapter | data/10건 → invalid/PAGE_MALFORMED | 실제 운영 읽기 + 자비스 코드 |
| 추가 frontmatter 필드 제거 후 다음 날 검사 | RECORD_IDENTITY_INVALID | 메모리상 응답·시계만 바꾼 원인 분리 실험 |
| signed remember → backup → restore | proved → backup 생성 → citation audit 실패 | 임시 저장소와 기존 요청 fixture |
| reference/status 무효값/2099년부터 검색 | 각각 9건 | 실제 저장소 읽기 |
| active scope 검색 | 0건, 코드상 일괄 빈 결과 | 실제 읽기 + 코드 확인 |

자비스 진단 스크립트와 로그: `/var/tmp/sb-backlog-20260907/`. 이전 회귀·복원 증거: `/var/tmp/sb-remediation-20260907/`. 임시 증거 경로는 영구 운영 백업과 다르다.

## 7. OSS 인계에 따른 추가 분석

- **R1 범위 보강:** inbox connector는 scan 과정에서 원장 확정 전에 `.done`으로 파일을 옮긴다. generation의 일괄 삭제만 제거해서는 capped·CAS 실패 시 접수 보존을 완성할 수 없다. 완료 이동의 시점을 함께 수정해야 한다.
- **R10 범위 보강:** `hybrid_search.query_cosine`은 vectors.db에 중간 테이블을 쓰며, `rrf_merge`는 SearchHit의 상태·출처 필드를 모두 보존하지 않는다. sealed 연결 전에 읽기 전용화와 메타데이터 유지가 필요하다.

2026-09-08 후속: 위 R10의 중간 테이블 쓰기·RRF 필드 유실을 재현해 수정했다. 없는 DB의 조회 중 생성, 모델/revision 불일치 허용, 제어문자 원문 손상도 수정했다. [검증 보고서](HYBRID-READONLY-2026-09-08.md). cosine 전용 출처/필터·세대 결합·삭제 수명·품질 평가는 남아 활성화와 R10 전체 완료는 보류한다. I1/G6의 task completion 수집도 원본 차단의 파생 기억 전파 계약이 없어 보류하며 자비스 `73d59df`에 재개 조건을 기록했다.

I1-d/G4 후속: V2 정정에서 여러 줄 content를 접수하고도 CRLF 변경으로 proof가 실패하거나 중간 문장 인용이 빠지는 결함을 수정했다. [V2 렌더링 보고서](CORRECTION-RENDERING-2026-09-08.md). 실제 MCP의 4개 문장·서명 검증·두 클라이언트 회수를 확인했다. V1 신규 remember의 일반 줄바꿈, 자비스 정정 후보/대상/승인/완료 전체 경로와 운영 인수는 남는다.
- **I7 범위 분리:** 1차는 자비스와 실제 사용 에이전트의 같은 기억 접근이다. 메일·기술·문서 등 다른 업무 실행자의 결과 연결은 후속이다.
- **G3 우선순위 상향:** 공통 context pack, 프로젝트 범위, byte/token 예산, session별 실제 전달 receipt, compaction 후 재공급을 앞당긴다.
- **중복 구현 제외:** 기존 FTS/cosine/RRF, 에이전트별 파서, CAS/원장, 요청·정정·삭제·복원 구조를 재사용한다. OSS별 별도 서버나 정본을 추가하지 않는다.
- **완료 기준 강화:** MCP 연결, 읽기, 기록, 로그 자동 수집, 자동 문맥 주입을 별개 능력으로 실측한다. A 기록/B 회수와 정정/삭제 반영까지 검증하며 특정 클라이언트 전용 훅을 공통 지원으로 보고하지 않는다.

### 후속 구현 상태

OSS 인계 병합과 함께 R1을 작업공간에서 수정했다. scan의 선제 이동을 제거하고 CAS·원장 확정 뒤 정확한 입력 버전에 대해서만 완료 통지를 한다. 세대 변경 때 미처리 inbox를 보존한다. 전체 테스트 520 passed / 2 skipped, Ruff 통과, BasedPyright 오류 0 / 경고 60. 상세 파일·증거는 [통합 계획 10절](OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md#10-이번-구현검증-결과)에 있다. 운영에는 아직 적용하지 않았으며 R2/R3/R4의 해소를 의미하지 않는다.

R2 추가 조율 사항: 자비스 resolveDuplicates는 page_id+sid 기준으로 여러 문장을 묶어, 같은 출처의 정상적인 서로 다른 record도 conflicts로 분류할 수 있다. metadata 계약 외에 record ID 기반 중복과 실제 사실 충돌의 구분도 자비스 작업에서 해결해야 한다.


## 8. 구현 후속 — 공개 응답과 요청 기억 출처

최신 세부 진행은 [구현 원장](IMPLEMENTATION-STATUS.md)에 기록한다. 기존 결함 설명은 수정 전 재현 증거이며 최신 동작은 이 절과 원장을 우선한다.

- R2: 내부 frontmatter 필드 유출을 고쳤다. 추가로 검색의 `wiki/foo`와 저장 metadata의 `foo`가 같은 파일임에도 SOURCE_ID_MISSING으로 거부되는 결함을 확인하고, 경로 동등성이 검증될 때만 공개 ID를 정규화했다. 실제 별도 MCP 프로세스에서 자비스 기존 adapter가 단일 기억을 current로 소비했다. 여러 사실을 같은 sid로 묶는 자비스 측 오판은 미완료다.
- R3: request remember가 원문 CAS·SourceCite·Vault writer를 사용한다. 동일 후보 재시도와 다른 후보의 동일 내용 출처를 구분하며 여러 줄 기록도 인용한다. 실제 executor의 proved 결과를 runtime backup으로 만들고 독립 경로에서 복원·CAS·페이지 바이트 일치를 확인했다.
- 추가 연쇄 결함: 정정이 기존 CAS를 제거한 뒤 페이지에 낡은 인용이 남았다. 의도적으로 제거한 CAS에 한해 생존 문장을 effect receipt에 연결된 새 스냅샷으로 재결합했고 remember→correct→export→forget 전 과정의 인용 감사를 추가했다.
- 전체 527개 통과, 2개 건너뜀. 운영 배포, R4 시간 의미, 실제 자비스 전체 업무 순환, 두 앱의 교차 기억 인수는 아직 남아 있다.


## 9. B2 후속 — 검색 의미와 읽기 일관성

R5/R7/R9의 소스 수정을 진행했다. Sealed 모드에서도 상태/날짜/종류 필터와 기존 승인 원장의 read-only 조회를 적용한다. title-only 결과와 중복 section을 건너뛴 뒤 record limit를 계산한다. CLI 조회는 고정된 generation과 reader lease를 사용하며 오류 종료에서도 해제한다. CLI pin 커밋은 `9ba9588`이다.

전체 534 passed/2 skipped, Ruff 통과, 타입 오류 0/기존 경고 55. 운영 자료를 새 소스 CLI로 읽어 날짜 필터의 포함/제외를 확인했다. 운영 release는 아직 전환하지 않았다. R6 reader 강제 종료 복구, I3 갱신 중 지연, R4 시간 및 자비스 중복 소비, 프로젝트 범위는 이 변경의 완료 범위에 포함하지 않는다. 상세 증거는 구현 원장 B2를 따른다.


## 10. B3 후속 — reader 종료 복구

R6의 종료된 reader lease 회수와 현재 전환의 정리 재개를 구현했다. 생존 여부만이 아니라 Linux boot/start identity로 PID 재사용을 구분한다. 과거 형식의 lease와 알 수 없는 생존 상태는 보수적으로 유지한다. 실제 reader 프로세스 SIGKILL 후 세대 전환/폐기, live reader 보존, PID 재사용, 유지보수 및 다음 mutation의 중단 정리 재개를 검사했다.

전체 540 passed/2 skipped, Ruff 통과, 타입 오류 0/기존 경고 55. 다만 실제 운영에는 디렉터리가 없는데 activated로 남은 과거 이력 2건과 잔여 generation 디렉터리가 존재한다. 기존 자료 대조/복구와 I3의 읽기 지연은 미완료이며, 이번 소스 변경을 그 해결 증거로 사용하지 않는다.

## 11. B4 후속 — 자비스 저장 완료와 명령 상태 연결

기존 CLI/dashboard outbox 구성 후 남았던 `settled / uncertain` 상태 불일치를 수정했다. 영수증·원래 실행 fence·완료 증거를 결합한 terminal 반영, 취소 보존, 재시작/만료/오류 복구, 순환 검사와 원문 없는 cursor 정리를 구현했다. 실제 격리 MCP·CLI API에서 control completed, 64개 sensitive record, 두 클라이언트 current, 재전송 0을 확인했다.

OSS 인계의 작은 공통 기억 순환을 우선 완성하는 변경이다. 운영 signed fence·후보/publication/UI·일반 LF/V2 정정·실제 앱별 수집/주입·project/user 범위·문맥 예산·운영 복원·한국어 품질/부하는 계속 미완료다. 수정/개선/고도화별 다음 목록과 검증 범위는 [명령 완료 연결 보고서](MEMORY-CONTROL-COMPLETION-2026-09-08.md)에 합쳤다.

## 12. I1 후속 — 삭제 이후 공통 기억 조회

기본 signed fence 구성을 CLI/dashboard/완료 reader에 연결하고, 실제 삭제로 드러난 빈 출처 목록의 공개 응답 결함을 수정했다. 삭제된 record 0개와 이후 새 sensitive record 64개의 저장 완료·두 MCP 클라이언트 재사용을 실측했다. 자비스 회귀 149개, Python 계약·삭제/복원 회귀 18개 통과. [변경·설정·검증과 남은 실행 목록](MEMORY-READ-FENCE-INTEGRATION-2026-09-08.md).

기본 서명 **소스 연결**은 완료, 운영 키 구성·release 인수는 남는다. 추가 검증 개선: 최근 변경 목록 `current`만 확인하면 빈 목록도 통과한다. 고정 테스트 시각과 Git `--since` host 시각을 일치시키고 expected page/record를 확인해야 한다. 이번 실제 저장 성공은 최근 목록 상태 대신 원문 페이지와 전체 record 대응으로 판정했다.

## 13. I3 후속 — 갱신 중 실제 기억 조회

writer mutex로 모든 generation writer를 직렬화하면서 sealed 부모에서 준비하는 동안 reader를 허용한다. MCP 조회의 유지보수도 busy 상태에서 기다리지 않게 했다. 실제 자비스 완료 cycle과 두 클라이언트의 64개 민감 record 회수를 컴파일 진행 중 약 1.4초에 검증했다. reader pin, writer kill 후 복구, 중간 삭제 접수 시 활성화/조회 거부, 만료 export 상태 거부와 후속 물리 정리를 검사했다. [원인·변경·검증 보고서](GENERATION-READ-CONCURRENCY-2026-09-08.md).

동시에 최초 remember의 필수 log/gitignore 초기화 누락을 수정해 바로 export할 때 inventory 검사를 통과하도록 했다. raw/.sb 강제 제외 규칙은 상속 negation보다 뒤에 두고 원문 CAS 보존과 Git 이력 제외를 검증한다.

**추가 개선/보류:** 과거 `.staging`/미활성 generation 일괄 삭제는 요청·원장·현재 writer 대응 검증 없이 실행하지 않는다(B3). 자비스의 signed export status/expires_at 소비는 신규 I1 후속이다. 이번 SB 만료 오류는 현 transport에서 일반 오류로 실패 처리된다. 운영 부하 p95·전환·실제 앱 인수는 계속 남는다.


## 14. I1-d/G4 후속 — 정정 완료 연결 및 재시도

provider의 정정 완료 이후 control이 claimed/uncertain에 남는 결함을 수정했다. 변경 사항·원인·남은 P1/P2 항목은 [정정 완료 연결 보고서](CORRECTION-CONTROL-COMPLETION-2026-09-08.md)에 상세히 기록했다. 과거 결함의 재현 설명을 현재 소스 상태로 읽지 않는다.

관련 회귀 34개 통과, 실제 정정 proved/control completed/두 클라이언트 4개 record/이전 기억 0개. 최종 event 실패와 20분 만료 후 복구 시 전송·compaction은 각 1회였다. 이는 운영 전환, 정정 UI와 모든 앱의 자동 기억 사용 완료가 아니다. 원본 task 차단 전파 없는 자동 수집과 근거 없는 hybrid 활성화는 계속 보류한다.


## 15. R8/I6 후속 — 운영 준비 상태와 검증 백업

mtime만으로 backup을 정상 판정하지 않는다. 격리 복원 검증 receipt와 현재 archive identity·생성/검증 시각·원 저장소/provider·삭제 이력을 대조한다. 새 백업 실패를 예전 정상 백업으로 가리지 않고, 마지막 run 경과·미해결 derivation·oldest request·최근 failure·journal/cleanup 상태를 code와 HTTP 503으로 표시한다.

전체 591 passed / 2 skipped, 실제 CLI/HTTP ready 503→200→503 및 health 200 유지, 관리형 CLI backup 검증을 확인했다. [보고서와 운영 설정](READINESS-VERIFICATION-2026-09-08.md). 실제 운영 배포/백업·독립 runtime 복원 인수, adapter receipt 결합과 I5 대용량 잠금·공간 검증은 계속 미완료다.

## 16. I1-d/I8 후속 — 본문 호환성과 완성 우선 목록

[인계 병합 후 상세 분석](SHARED-MEMORY-COMPLETION-REVIEW-2026-09-08.md)에 수정·개선·고도화 14개 실행 묶음을 기존 ID로 정리했다. 추가 재현: 일반 LF/CR은 후보/요청/접수에서 거부되며, 선행 BOM/NEL에서 Python과 JS 판정이 반대다. 후보 본문 검사를 통과해도 저장 record 수/이스케이프 후 크기 제한에 걸리는 사례가 있다.

실제 두 언어의 검증기와 isolated stable 접수 12개 대조, 수락 4개 정확 재시도·원문 불변, 거부 8개 요청 파일/DB 미생성을 확인했다. 본문 기능 수정·새 버전 도입은 아직 아니다. 후보 원문부터 승인·요청/재시도·원장 migration·처리·복원·완료 검증까지 함께 바꾸며, 기존 V1/기존 V2 effect 계약 우회는 보류한다.

## 17. I1-d 구현 — 명시적 일반 텍스트 V3

16절의 신규 계약을 구현했다. 새 후보 입력 schema2/plain-text-v1을 review/dispatch·권한·provider request3·MCP schema5에 결합하고, 기존 V1/V2와 frozen schema4는 유지한다. 일반 LF/CRLF/CR/탭·공백·반복·footnote의 전체 원문과 결과를 대응한다. 같은 원문/출처의 프로필 변경 중복도 차단했다.

함께 발견한 접수 orphan의 시간 변경 충돌을 원래 파일·시각/digest 채택으로 복구하고, 실행 전 원장 접수 digest와 전체 envelope를 대조한다. 두 원장의 migration은 기존 데이터·FK·제약을 보존한다. 전체 Python 621 passed/2 skipped, 실제 CLI/MCP에서 혼합 4개 및 일반 LF 64개 sensitive record·두 클라이언트·명령 완료·stored=true, 삭제 이후/rollback/컴파일 중 조회를 검증했다. [정확한 검사 결과·시간 초과 재검·설정·한계](REMEMBER-V3-ACCEPTANCE-2026-09-08.md).

일반 여러 줄의 소스/격리 인수는 완료이며 운영 활성화는 아니다. I8 추가: 기존 자비스 권한 만료 경계 테스트가 9개 DB 생성 시나리오를 하나의 5초 검사로 묶어 부하 중 timeout을 냈다. 동일 조건 단독 재검은 통과했으며 후속으로 같은 시나리오를 개별 테스트로 분리해 원인을 명확히 표시한다. 정정 UI·실제 앱/범위·context pack·원본 차단 전파·운영 복원/부하/검색 품질은 유지한다.

## 18. I5/I8·R8 후속 — 구조 부하 인수와 봉인 저장소 조회/생성

[대용량 인수 보고서](CAPACITY-ACCEPTANCE-2026-09-08.md)에 실제 5,000 원본→100,000 units, 10,000 page/1,000 conflict fixture, 100회 CLI 읽기, 관리형 백업/새 경로 복원 결과를 기록했다. 전체 CAS 5,000개 보호, orphan/invalid 0이며 복원 후 검색·원장 수·CAS 감사가 일치했다. 이는 100회 예약 쓰기나 한국어 품질 인수를 대체하지 않는다.

실제 발견 결함 두 개를 수정했다. 봉인 원장의 보존 조회가 writer를 열던 경로를 read-only SQL로 바꿨다. 파생 records/FTS 행별 commit을 묶어 세대 생성은 이번 단일 비교에서 59.36→23.78초로 줄었다. 메타데이터 삽입 실패 시 rows rollback·기존 세대 유지·재시도 성공을 검증했다.

**I5/P1 추가 결함:** `max_new_units_per_run=1`에서도 파일 1개가 unit 20개로 저장되고 `ok`다. 제한이 source attempted 수에 적용된다. 파일 수/실제 unit 예산을 분리하고 잔여 예산 초과 원본의 보존/재개와 CLI 호환을 같이 고친다. 이 경계를 확인하기 전 자동 대량 온보딩·운영 cap 증대는 보류한다. 기존 24개 ID 및 B4~B8 미완료 범위는 유지한다.

## 19. I5 수정 — 신규 unit 예산과 원본 완료 경계

18절에서 재현한 cap 결함을 수정했다. `max_new_units_per_run`은 원장 신규 고유 unit 수, `max_source_items_per_run`은 원본 버전 처리 시도 수로 분리했다. 기존 `--limit`은 원본 수 의미를 유지하고 unit cap을 우회하지 않는다. 초과 원본을 부분 완료하지 않으며 원본·cursor를 보존한다. 전체 예산 초과는 실패로 알리고, 잔여 예산 초과는 다음 실행에서 이어간다.

실제 관리형 `remember→ingest` CLI에서 cap 1의 큰 원본 보존/작은 원본 처리, 예산 조정 후 복구, 12/12/8의 두 차례 분할 처리 및 재실행 증가 0을 검증했다. 최종 source 5/unit 53·원문 일치·orphan/invalid 0. 5천 source/10만 unit 구조 부하도 명시적 예산으로 재검증했다. [계약·검사·증거·한계](INGEST-BUDGET-CONTRACT-2026-09-08.md).

부분 unit 저장은 별도 완료/보호 계약 없이 활성화하지 않는다. 운영 배포·cap 증대는 하지 않았고 100회 managed 쓰기, 대용량 동시 조회/성장·한국어 품질 및 B4 실제 앱/접근 범위·B5 문맥 공급은 유지한다.

## 20. I1/I7·B4 후속 — 실제 client 간 공유와 범위 계약

Codex CLI 0.153.4와 Claude Code 2.1.261에서 같은 격리 기억 저장소의 양방향 기록·회수를 검증했다. 성공 MCP 6건, source 2개, 원문 CAS 일치와 검색/page의 generation·record ID/digest 일치다. CLI exit 0이면서 도구는 승인 오류로 실패하는 경우를 실제 재현하여, native 이벤트/결과/최종 답변을 대조하는 감사기를 추가했다. [실제 인수 보고서](AGENT-CLIENT-MEMORY-ACCEPTANCE-2026-09-08.md).

README의 일반 stdio sb_run 안내를 실제 노출 도구와 맞췄다. batch/fixture compile·단일 owner/genesis 인수이므로 실제 자동 수집/주입, GUI·다른 client, 삭제 이후 일반 agent fence, 운영 연결은 남는다. project/user/agent 범위는 [구현 전 ADR](SHARED-MEMORY-SCOPE-ADR-2026-09-08.md)의 자비스 발급·SB 소비 및 출처 분류/수명주기를 함께 구현한다. active/reference 검색 필터만으로 접근 격리를 주장하는 구현은 보류한다.

## 21. B4/B7 후속 — 배치 완료와 실제 회수의 불일치 수정

대용량 반복 쓰기 도구의 70개 충돌 선행 실행에서 `sb run`은 성공했으나 daily MCP 조회는 `MEMORY_RECORD_PAGE_OVERSIZE`였다. 브리핑의 입력/추천을 기존 64개 레코드 계약 안에서 제한하고 생략 수를 표시한다. 원본과 개별 기억은 보존한다. 이어 재현한 `.sb/compiled` 해시 승계 누락과 제안만 저장된 결과의 완료 오판도 수정했다. 사람 수정본의 반복 보호와 구버전 생성본의 실제 갱신을 검사했다. [결함·수정·증거](BRIEFING-RECORD-BUDGET-2026-09-08.md).

실제 3회 capture/run·동시 MCP 검색/원문·백업 복원은 작은 선행 인수다. `scripts/write-cycle-acceptance.py --full`의 5천 원본/10만 units/1만 wiki/1천 conflict와 100회 실제 쓰기, B4 scope·일반 agent fence·정정 UI, B5 공통 문맥 공급, B6 운영 인수, 한국어 품질과 B8은 남는다. 기존 잘못된 완료/해시 이력을 무조건 자동 승인해 복구하는 기능은 보류한다.

## 22. I5/B7 후속 — 충돌 후보 전수 계산 병목

원본 5천 개/10만 units의 첫 full 배치에서 모든 unit마다 전체 문서 빈도표를 재구성하는 병목을 확인했다. 256 units에서 65,280회 빈도표 생성이 재현됐고, 해당 격리 실행을 의도적으로 중단한 뒤 수정했다. 기존 점수/동점/중복 규칙을 유지하는 역색인과 실행 내 제한된 캐시로 최종 10만 단위 후보 계산은 프로파일 포함 10.56초였다. 실제 기존 접수 건의 배치 재실행도 102.67초에 완료되어 source 5,001/units 100,001와 원문·MCP 회수를 확인했다. [근거·한계](CONFLICT-CANDIDATE-CAPACITY-2026-09-08.md).

전체 100회 인수는 새 버전의 새 격리 실행으로 이어간다. 기존 실패를 통과로 바꾸거나 첫 1회를 100회로 대체하지 않는다. 전역 상위 10쌍의 새 기억 검토 누락 가능성, 다양한 질의의 최악 비용, 강제 종료 staging 정리, 전체 배치·capture 지연과 한국어 평가를 남긴다. 이 결과만으로 운영 cap/자동 대량 온보딩을 확대하지 않는다.

## 23. G2/I7·B7 후속 — 한국어 질문의 미회수 기준선

[한국어 검색 평가](KOREAN-SEARCH-BASELINE-2026-09-08.md): 합성 문서 20개/질문 100개에 실제 CLI/MCP를 실행했다. 정답 있는 90개 중 40개 회수, 어순 변경·자연어·의역 50개 미회수를 확인했다. 정확한 문구와 키워드는 상위 5개에 모두 회수됐으며, 선택 record/출처·세대 42건 대조와 관련 회귀 42 passed다. 이 결과를 실제 사용자 전체 검색 정확도나 100–300개 실사용 질문 인수로 확대하지 않는다.

P1으로 봉인/비봉인 질의 처리와 MCP record 선택의 의미 일치, 정확한 문구 보존·어순 변경 개선·잘못된 주제 회수 측정을 추가한다. 실제 사용자 질문·어려운 무정답·정정/범위 사례 확보, B5 context pack/실제 전달 이력과 B8 근거/세대/삭제 결합은 유지한다. 하위 검색만 바꾸거나 record/generation 검사를 완화하는 우회, 품질 측정 없이 hybrid/graph 일괄 활성화는 보류한다.

## 24. G2/I7 후속 — 공통 질의와 record 선택 구현

[검색어 어순 수정](KOREAN-QUERY-CONSISTENCY-2026-09-08.md)은 기존 trigram에 모든 검색어 AND를 적용하고 봉인/비봉인/record 선택을 같은 모듈로 연결한다. 같은 페이지의 다른 record를 합쳐 근거로 삼지 않으며 선택 후 limit·fence·ID/digest를 유지한다. 합성 100질문의 회수는 40/90→60/90, 어순 변경 20개 회수다. 전체 문구 정답은 1위를 유지했으나 추가 참고 후보도 2개 늘어 이득과 확장 영향을 함께 기록했다.

대규모 쓰기 인수와 분리한 worktree에서 구현/검증하며 원 작업공간 병합은 해당 실행 뒤 수행한다. 자연어/의역 30개 미회수, 실제 질문 확보, 전체 문구 강제 모드, 혼합 문자/형태소 처리·복잡한 질의 비용, B4 접근 범위·B5 전달·B6 운영·B8 삭제 결합은 계속 남는다.

## 25. B3/I5 후속 — 프로세스 종료 후 미봉인 원본 사본 정리

[준비 세대 복구](STAGING-RECOVERY-2026-09-08.md): 다른 ID의 성공한 재실행에도 남던 staging 사본을 기존 단일 writer와 유지보수 진입점에서 정리한다. 위험한 경로·열린 descriptor·살아 있는 writer는 삭제하지 않으며, 정리 실패와 재시도를 관측한다. 실제 CLI/프로세스 종료/유지보수/두 기억 MCP 회수·원문 보존, 전체 733 passed/2 skipped다. 원 작업공간의 대규모 인수 후 병합하며 운영 잔여물에 무조건 적용하지 않았다.

B5는 자비스에 이미 있는 문맥 snapshot/근거/삭제 projection을 재사용해야 한다. SB에 별도 전달 원장을 추가하는 중복 구현은 하지 않는다. 세션 전달·중복·compaction과 범위, 자연어 검색·전체 삭제/복원·운영 인수의 기존 남은 범위는 유지한다.

## 26. G2 후속 — 정확한 문구 지정과 입력 예산

[문구 검색 인수](SEARCH-PHRASE-ACCEPTANCE-2026-09-08.md): AND 검색이 추가 후보를 반환할 때 큰따옴표 그룹으로 연속 문구를 지정할 수 있도록 했다. 인용문과 경로를 보존하고 4,096 UTF-8 bytes/32그룹을 넘거나 잘못된 문구는 명시적 오류로 처리한다. 실제 CLI/MCP의 문구 7/7 회수·무정답 3건, 기존 합성 100개 60/90 회수 유지, native CLI 3/MCP 5 오류 반환을 검증했다.

이는 질의 입력 경계다. 실제 질문·자연어/의역·혼합 문자 처리와 공통 context pack/전달 이력은 남는다. 앞선 검색/복구 수정과 함께 격리 worktree에 구현하며 원 작업공간 100회 쓰기 인수 종료 후 병합한다.


## 27. G3/B5 후속 — 실제 문맥 공급 경계 대조

[상세 분석과 C1~C8](CONTEXT-DELIVERY-GAP-ANALYSIS-2026-09-08.md)에 인계서와 자비스 기존 assembler/adapter/context store/projection을 병합했다. 새 격리 빌드에서 confirmed snapshot의 본문 부재, provider untrusted 제외, LF/CRLF/CR/tab 거부, 기억만 있을 때 live 관측 부족, 본문 길이가 총량에 반영되지 않음을 재현했다.

우선순위는 공급 목적·신뢰 계약 → 원문 보존/최종 payload 예산 → 실제 전달 receipt·session/compaction → 삭제/정책/프로젝트 범위 결합이다. 기존 추천 조건을 완화하거나 trust를 올리고 별도 원문 DB를 만드는 우회는 보류한다. 진단 도구 exit 0은 결손 재현이며 B5 구현 또는 실사용 인수 통과가 아니다. 기존 100회 쓰기와 병합 대기 세 커밋, B4~B8 전체 완료 조건을 유지한다.


## 28. G3/B5 구현 — 원문과 출처를 보존하는 문맥 준비

자비스 `3360fe7`의 [참고 기억 묶음](MEMORY-REFERENCE-PREPARATION-2026-09-08.md)은 C1~C5의 준비 단계를 구현한다. 추천용 live/confirmed 계약을 유지하고 별도 reference-only 프로필에서 provider untrusted 원문·digest·세대를 보존한다. 최종 JSON 예산·전체 항목 생략·상충 출처와 세대 거부를 검사했다. 관련 94 passed, 실제 MCP 인수 및 독립 리뷰/수정/재검토 완료.

실제 tokenizer/model 전달·전송 receipt·로컬 suppression와 범위·세션 중복/compaction·삭제 계보 연결은 여전히 필요하다. 라이브러리 export를 전역 자동 주입 완료로 취급하지 않는다. 제품의 원문 DB·승인 엔진·frozen MCP는 추가/변경하지 않았다.


## 29. G3/B5 구현 — 실제 CLI 조회와 정책 변경 감지

자비스 `63bdd02`의 [참고 기억 조회](MEMORY-REFERENCE-READ-2026-09-08.md)는 준비 JSON을 명시적
CLI에 연결하고 기존 로컬 차단·signed read/status·세대·만료 검사와 최종 stdout 예산을 결합한다.
같은 개수 REPLACE, 중복 cleanup/오류 덮어쓰기, DB/키 close 오류를 재현·수정했다.
최종 77개 관련 회귀와 실제 CLI/MCP 5시나리오, 독립 재검토 통과.

C6의 모델 수신/session/compaction receipt, C7의 전송 후 삭제·정정 수명, C8의 검증된 범위와
B4 자동 수집 보류·B6 운영·B7 full100/질문·B8 품질을 계속 유지한다. provider_status_received_at은
관측 시각이며 영속한 freshness 보증이 아니다. 운영 migration 070은 미적용, 새 원문 DB와
자동 주입은 추가하지 않았다. 최종 상세 표의 우선순위·완료 증거를 후속 개발 기준으로 삼는다.


## 30. B5/C1 인수 — 실제 모델 요청에서 본문·근거 회수

[실제 모델 인수](MEMORY-REFERENCE-MODEL-ACCEPTANCE-2026-09-08.md)를 추가했다. 자비스 CLI
출력→native Codex 요청에서 무작위 값과 출처를 정확히 회수했고 도구 없는 빈 기억은 no_data다.
exit 0을 성공으로 오인하지 않도록 native 이벤트 감사와 14개 실패/정상 검사를 구현했다.

자비스 작업 prompt의 승인 plan/source_files, --no-session-persistence, 추천용 context 저장
계약을 대조했다. 이를 그대로 C6 session 전달/compaction 기록으로 쓰는 우회는 보류한다.
C7 전송 수명/삭제, C8 범위와 기존 운영·성능·품질 완료 조건을 유지한다.


## 31. B8/R10 수정 — cosine 후보의 현재 메타데이터와 필터

[필터·출처 수정](HYBRID-FILTERS-2026-09-08.md), 격리 `ef3466e`: 전처리 조건 없이 cosine 상위
결과를 합치던 결함 4건을 재현했다. 현재 본문 대조·같은 필터·제한 전 거리 순위·메타데이터 복원을
구현했고 전체 775 passed/2 skipped와 실제 CLI를 검증했다. source/상태 필터와 물리적 거리 오류는
정상 결과로 우회하지 않는다.

봉인 세대에 vector/identity/삭제 수명을 결합하고 실제 질문·성능을 평가하기 전 운영 활성화는
보류한다. 지식 scope를 프로젝트 접근 권한으로 해석하지 않는다. 100회 쓰기 종료 후 병합 대기는
기존 3개에서 4개 커밋으로 늘었으며 나머지 완료 조건은 유지한다.


## 32. B8/R10 수정 — 재생성 실패가 기존 벡터 DB를 없애는 문제

[원자적 벡터 재생성](VECTOR-REBUILD-ATOMICITY-2026-09-08.md), 격리 `5d25d3a`: 실패 재현 4개,
기존 DB를 보존하는 별도 생성·검증·교체와 대량 SQL stream, 동일 commit 수집, writer 충돌·봉인
변경 거부를 구현했다. 전체 797 passed/2 skipped, 실제 CLI 131 vectors 및 hybrid 5시나리오 통과.
SQL에 전달하는 CRLF/한글/NUL의 바이트 보존과 실제 강제 종료 후 다음 rebuild를 확인했다.

남은 P1은 generation enabled=0/manifest/reader pin/삭제·복원 결합, Git·registry 동시 수명,
상주 모델·배치/메모리 상한, 소유권을 확인한 강제 종료 잔여 DB 회수, 실제 한국어 평가다.
단독 rebuild를 managed hybrid 완성으로 계산하지 않는다. 원 작업공간 full100 완료 뒤 다섯
커밋을 순서대로 병합한다. 기존 B4~B8 및 운영·자비스 자동 문맥 전달 보류는 유지한다.


## 33. B7 인수 완료 및 B8 선행 무결성 수정

[대규모 100회 쓰기](WRITE-CYCLE-ACCEPTANCE-2026-09-08.md): 모든 주기의 실제 동시 MCP 읽기,
신규 기억·CAS·record/세대 확인과 최종 무변경 run·100개 복원 회수가 통과했다. 소스 고정을
해제하고 대기 다섯 커밋을 병합했다. MCP 검색/읽기 각 312,407회이며 capture/run의 높은
p95 32.99/112.66초는 별도 P1 성능 항목으로 유지한다.

[봉인 파일 무결성](GENERATION-INTEGRITY-2026-09-08.md), 원 작업공간 db94997: 저장된 파일
해시와 실제 DB 불일치, manifest 자체 digest와 목록 누락을 거부한다. CLI traceback 오류와
정상 복원 권한 호환도 수정했다. 전체 815 passed/2 skipped, 병합 후 26 passed, 실제 자비스
CLI 5건 및 새 3회 쓰기/두 MCP/복원 인수가 통과했다.

다음 필수 개발은 봉인 vector 논리/물리 binding 및 reader pin·삭제/복원, 쓰기 비용 프로파일링,
자비스 C6~C8 전달 수명/범위 계약이다. 실제 질문·GUI/운영 인수 조건도 남는다. stored inventory
검사를 별도 서명 권한이나 모든 원문/SQL 행의 논리 감사로 확대 해석하지 않는다.


## 34. B7/P1 쓰기 지연 — 실제 프로파일과 세대 복사 최적화

[프로파일·수정·검증](GENERATION-WRITE-PERFORMANCE-2026-09-08.md), 제품 `fe21016`: 제외되는
.git/.sb 내부 순회를 생략하고 상대 경로를 재사용하며, 복사 중 조기 fsync를 최종 봉인 전수
동기화에 모았다. 포함 파일 검증과 단일 writer·pin·fsync 실패 시 이전 세대 보존을 유지했다.
동일 고정 입력의 generation manifest는 기준 코드와 같았다.

대용량의 분리 단일 프로파일에서 remember 33.52→12.24초, run 120.06→96.83초. 전체
821 passed/2 skipped와 실제 3회 쓰기/두 MCP/복원 통과. 새 100회 부하의 p95로 주장하지 않는다.

남은 큰 비용은 원본 전체 재정규화, 두 차례 전체 unit 보호 처리, conflict/briefing의 corpus
스캔이다. 정책 결과가 같은 빠른 보호 경로와 실제 전송 대상의 중복 처리를 먼저 검증한다.
정규화 cache는 parser/source/version·삭제 수명 계약 전까지, capture를 별도 inbox/queue로
옮기는 변경은 generation 응답 계약을 보존하기 전까지 보류한다. 기존 전체 미완료 범위는 유지한다.


## 35. B7/P1 반복 보호 처리의 결과 보존

제품 `b6d9875`, 전체 860 passed/2 skipped, Ruff/변경 파일 타입 검사 통과.

[정규식 빠른 경로·동등성·실측](REDACTION-PERFORMANCE-2026-09-08.md): 일치에 반드시 필요한
문자가 없을 때 해당 치환만 생략한다. 정규식/치환 순서와 source 정책 검사, 원문 연락처 보존,
기존 LLM 사본 보호는 유지했다. 고정 사례와 2,000개 Unicode/중첩 조합으로 이전 결과를 대조했다.

같은 대용량 fixture의 단일 CLI 프로파일에서 run 96.83→74.07초, mask_sensitive 누적
22.93→2.68초였다. remember는 12.24→12.52초로 개선을 주장하지 않는다. 공유 호스트 부하와
profiler 비용을 포함하며 운영 p95가 아니다. 신규 기억 회수와 두 MCP/3회 쓰기/복원도 통과했다.

재정규화·완료 compile의 전체 처리·conflict/briefing 비용과 기록 응답 지연은 남는다.
검사 자체 생략·원문 캐시·별도 queue는 정책/버전/삭제·세대 계약 검증 전까지 보류한다.
자비스 session 전달/삭제/범위, 봉인 의미 검색·실제 품질·GUI/운영 인수의 미완료 조건을 유지한다.


## 36. B8/P1 벡터 재생성 경로와 종료 복구

제품 `d152819`, 최종 전체 874 passed/2 skipped, Ruff/변경 파일 타입 검사 통과.

[경로 보호·복구·보류 상세](VECTOR-RECOVERY-SAFETY-2026-09-08.md): `.sb` 링크가 외부 DB를
덮어쓰는 경로와 디렉터리 교체 후 게시/정리 문제를 재현했다. private vault/디렉터리 inode 검증,
descriptor 기준 생성·게시·정리, 사후 SQL 검사까지 writer 잠금 상속을 적용했다.
replace 후 fsync 실패는 이미 교체됐으나 내구성 미확정인 상태로 구분한다.

97 passed/1 skipped 집중 검사, 실제 SQL 완료 후 강제 종료→기존 검색→CLI 재시도·reader
이전 3행/새 4행 및 기존 hybrid 필터/정정 5시나리오 통과. 정상 0700 vault 아래 inner 0775
권한 호환도 수정했다. 최초 권한 실패와 중단 회귀는 최종 통과와 구분한다.

**자동 회수 보류:** 같은 UID의 열린 FD를 모두 확인할 수 없는 호스트에서는 임시 DB를 보존하고
경고 후 새 rebuild를 허용한다. 실제 인수에서 잔여 1개/cleanup_complete=false였다.
확인 가능한 열린 파일·위험한 링크/권한은 거부하며 무조건 glob 삭제하지 않는다.
봉인 의미 검색·MCP의 의미 record 선택·삭제/복원·실제 질문 품질과 B4~B8는 계속 미완료다.


## 37. B8/P1 봉인 의미 검색과 기억 수명 결합

제품 `cbb910d`, [구현·실제 프로세스 인수](SEALED-VECTOR-ACCEPTANCE-2026-09-08.md).
기존 관리형 vector enabled=0 고정을 해소했다. 명시적 hybrid writer가 cited record 벡터를
같은 generation에 봉인하며 모델/본문/벡터 digest와 기존 물리 inventory를 연결한다.
이전 세대의 동일 record만 재사용하고 정정·삭제·모델 장애 시 이전 vector를 새 DB에 남기지 않는다.
MCP schema 4/5의 의미 후보는 실제 원문 record와 다시 대조하고 RRF로 중복을 제거한다.

전체 893 passed/2 skipped, 집중 50 passed/1 skipped, Ruff/타입 통과.
두 실제 MCP 프로세스의 같은 기억 회수, CLI 정정/삭제 state=proved, 각 상태의 백업/별도 경로
복원과 원문 인용 감사가 통과했다. 결정적 encoder이며 실제 한국어 모델 품질 검증은 아니다.

다음 필수 항목은 실제 질문 100–300개와 무정답/낮은 관련성 처리, 모델 배치별 프로세스 비용,
대규모 cosine 지연 및 운영 가시성이다. 기본 false/운영 활성화 보류를 유지한다.
자비스 C6–C8와 프로젝트 접근 범위·자동 수집·실제 GUI/운영/DR의 기존 조건도 유지한다.


## 38. B8/P1 실제 모델 실행 경계와 품질 기준선

제품 `0834e86`, 도구 `6b32416`: [실제 모델·수정·인수](REAL-EMBEDDING-PROCESS-2026-09-08.md).
부분 캐시에서 온라인 로딩을 허용하던 경로, subprocess 무제한 대기, 비숫자 출력 ValueError를
재현해 offline 인코딩·60초 실행 한도·기존 EmbeddingUnavailable로 수정했다.
전체 897 passed/2 skipped, 집중 54 passed/1 skipped, Ruff/타입 오류·경고 0.

실제 BGE-M3를 사용한 CLI/MCP에서 자연어·의역 각 1건은 정답 1위지만 무정답 1건은 후보
5개가 반환되고 검색은 약 6초였다. 낮은 관련성의 제외와 query/batch별 모델 재로딩 비용이
필수 개선이다. 임의 threshold·에이전트별 상주 모델 증설·운영 활성화는 보류한다.

같은 합성 100질문의 lexical 재측정은 60/90 회수·무정답 10/10 빈 결과. 실제 모델 100질문은
별도 고정 worktree에서 진행 중이며 종료 전 전체 품질 수치를 주장하지 않는다.
실제 사용자 질문·자비스 C6–C8·접근 범위·운영/DR의 기존 전체 범위는 유지한다.


## 39. B8/P1 실제 검색 회수율·무정답·유사도 제어

제품 `7deb1b9`: [실제 모델 100질문 완료와 후속 인수](SEMANTIC-RELEVANCE-2026-09-08.md).
진행 중이던 고정 소스 평가가 종료됐다. 일반 검색 대비 회수는 60/90→90/90으로 늘었지만
무정답 10개에도 후보가 반환됐고 CLI/MCP p95는 약 6.3–6.5초였다.

같은 최소 cosine 설정을 봉인/비봉인·CLI/HTTP/MCP의 의미 후보 정렬/limit/RRF 전에 적용한다.
잘못된 설정은 거부하고 lexical 결과는 유지한다. 전체 919 passed/2 skipped, optional 포함
85 passed/1 skipped, Ruff/타입 통과. 실제 0.55 설정의 작은 3사례와 누락 정보 10사례 인수 완료.

유사도와 답의 존재 여부는 다르다. 알려진 주제의 누락 정보 10개 중 9개에 후보가 남았으므로
전역값 채택과 운영 활성화는 보류한다. 실제 모델 소비의 근거 충분성/무정답과 사용자 질문,
model 재로딩·총메모리, 자비스 C6–C8/범위·운영/DR의 기존 조건은 여전히 필수다.


## 40. B7·B8/P1 세대 생성의 모델 재사용과 실제 수명주기

제품 `701e966`: [배치 개선·인수·8개 잔여 우선 과제](EMBEDDING-BATCH-ACCEPTANCE-2026-09-08.md).
64개마다 모델을 새로 읽던 경로를 한 미게시 세대 안의 순차 재사용으로 개선했다. 기존 두 잠금을
자식에 상속하고 timeout·손상/과대 응답·비정상 종료를 회수한 뒤 봉인한다. 모두 재사용 가능한
레코드라면 모델을 시작하지 않는다. 전체 931 passed/2 skipped, 집중 58 passed/1 skipped,
Ruff/타입 통과. 실제 모델 129개 출력은 byte 단위 일치, 총시간 28.75→16.81초(단일 측정).
실제 모델로 두 MCP/CLI 정정·삭제·각 백업 복원도 통과했다.

이 개선은 개별 검색의 약 6초를 줄이지 않고 상주 모델을 추가하지 않는다. 직접 Transformers
대체는 작은 단일 초기화 이득으로 도입을 보류했다. 다음 우선 단위는 자비스 C6/C7의 전달·
compaction·삭제 수명이다. C8 범위 분류와 자동 수집의 원본 차단 전파, 실제 사용자 질문·근거
충분성·검색 지연·GUI/운영/DR의 기존 전체 완료 조건은 유지한다.


## 41. B5/C6·C7 실제 모델의 정정·삭제와 과거 문맥 사본

인수 도구 `8cb5dd5`: [실제 소비 5건과 남은 경계](REFERENCE-MODEL-LIFECYCLE-2026-09-08.md).
자비스의 새 격리 빌드와 실제 CLI/MCP/모델에서 최초 값→정정 새 값→삭제 no_data가 통과했다.
자비스 V2 요청과 SB proved 결과의 proof/관측 검증도 통과했다. 별도 원문 사본을 다시 보내면
모델은 과거 값을 답했다. provider의 새 조회는 계속 record 0개이므로 SB 재색인 부활과 구분한다.

제품 전달 관련 context/projection 세 테이블은 0행이었다. 기존 읽기 CLI에 전달 이력이 연결되지
않은 조건이며 C6/C7은 미완료다. [구현 전 전달 수명 계약](REFERENCE-DELIVERY-LIFECYCLE-CONTRACT-2026-09-08.md)에
준비/제출/확인/불확실/무효화, 중복 claim, 실제 epoch/compaction, 삭제와 늦은 확인의 경합,
새 세션과 복구의 완료 조건을 명시했다. 전역 자동 주입은 이 연결 전까지 보류한다.
회귀 18개·event 감사 14개·Ruff/타입/syntax 통과. 실제 운영·GUI·접근 범위·사용자 질문과
전체 runtime DR의 기존 완료 조건은 유지한다.


## 42. B5/C7 문맥 제출 전후 재검사 구현

자비스 `8e233c7`, SB 도구 `4e3a8de`: [보호된 제출 인수](REFERENCE-SUBMISSION-ACCEPTANCE-2026-09-08.md).
reader 발급 객체의 정확한 본문과 generation/privacy를 내부에 결합하고 객체당 한 번 submit한다.
전송 직전·callback 완료 뒤 상태/만료를 검사한다. 빈 결과도 최대 60초이며 변조/복사/다른 reader,
동시 호출·불확실 실패 후 같은 객체 재시도를 거부한다. 별도 원문 DB나 MCP wire 변경은 없다.

관련 70개/event 감사 14개/tsc/lint·독립 검토 통과. 실제 모델에서 준비 후 정정은 미전송,
callback 중 삭제는 결과 반환 거부, 이미 제출한 사본은 미전송을 확인했다. 최신 값/삭제 no_data는
유지했다. 기존 CLI JSON을 밖에서 직접 전송하는 경로는 guard 적용 밖이다. C6 영구 claim·receipt,
실제 session/compaction/삭제 계보와 앱 연결, 범위·사용자 질문·운영/DR의 미완료 조건을 유지한다.


## 43. B5/C6·C7 영구 전달 원장과 실제 재시작 검증

자비스 `6e101fc`, SB 도구 `fd9df47`: [구현·인수·잔여 14항목](REFERENCE-DELIVERY-JOURNAL-ACCEPTANCE-2026-09-08.md).
객체 단위 submit을 유지하며 필수 session의 submitInSession을 추가했다. 기존 AuthorityDb에서
키 고정·한 시도 claim·중복/불확실 차단·정책/삭제 transaction의 세션 무효화와 token 제거를
구현했다. 6파일 90개, 추가 upgrade/clock 집중 14개 통과. 실제 프로세스 강제 종료와 재시작,
fresh DB에서 이전 세션 차단 및 대상 HMAC 8개 byte 불검출, native 모델 5회 원장 상태 확인.

native 모델 실행에 사용한 session ID는 합성 adapter 값이다. 실제 앱의 session/compaction
관측과 수신 fence는 미완료다. 외부 전송과 DB의 전역 원자성, 범위·자동 capture·근거 충분성,
운영/DR 전체 완료를 주장하지 않는다. 다음 순서는 실제 앱 adapter와 검증된 범위 연결이다.


## 44. B5/C6·C7 실제 native 세션과 추가 원문 보존 표면

SB `94ea45a`: [실제 UUID 인수·native SQLite 잔류](NATIVE-SESSION-ACCEPTANCE-2026-09-08.md).
실제 UUID 5개, bootstrap 5회 + resume 5회 통과. JARVIS `6e101fc` 원장의 중복·무효화 세션 재개 차단 확인.
Node 20개/Python 12개 통과. 원장 상태는 callback_completed이며 native 확인 영수증의 제품 저장과 동일하지 않다.

provider 삭제 후 rollout 3개 외 thread_history_1.sqlite에도 확인값이 남았다. 다음 managed surface
계약은 이 DB·부속파일·rollout·백업을 함께 포함해야 한다. ephemeral resume도 원문이 남았으므로
옵션 이름을 비보존 보장으로 사용하지 않는다. native 상태 감사는 권한 예외 1개로 exit 1이며 전체
정상/삭제 완료로 격상하지 않는다. 실제 앱 연결·범위·compaction·자동 capture·운영/DR은 계속 미완료다.

## 45. B5/C7 JSON 직렬화 사본의 삭제·재유입 누락 수정

[구현·검증·15개 후속 우선 과제](JSON-RETENTION-ACCEPTANCE-2026-09-08.md)에 인계와 기존 목록을 병합했다.
자비스의 raw-only 검사를 원문/1중/2중 JSON byte 표현으로 확장했다. UTF-8 오탐 방지·임시 버퍼
소거·100k items/64MiB 누적 상한·비동기 callback 거부를 공통 helper에 적용했다. 기존 schema/wire 유지.
수정 전3실패→8파일35통과, 최종 guard 후3파일10통과. 실제5프로세스 인수로4사본 제거,
무관 파일 보존과 영구지문을 이용한 복원SQLite 재유입 거부를 확인했다. 삭제 자체는 원문이 필요하다.
제품 native root 연결·전체 직렬화/DB page 분절·운영/DR·scope 등 기존 완료 조건은 유지한다.

## 46. B4/B6 실제 기억 화면의 개인정보 수명과 시작 설정 결함

JARVIS `53136d4`, SB `bc3313b`: [수정8항목·검증·남은 경계](DASHBOARD-MEMORY-LIFETIME-2026-09-08.md).
검색/상세/충돌의 전체 privacy/session snapshot, suppression과token transaction, 현재token 기반
detail, 검색만료/epoch, query/draft clear, 이전 action completion 및 정상 검색 메시지 회복을 수정했다.
Dashboard211 및 최종집중6, backend관련15 및 최종6 통과(중복). 실제Chromium2viewport/HTTP경합409 인수.
전역 연결배지 끊김·provider는fixture라는 한계를 유지한다. 신규 P1: remote-approval compose가
cwd 상대정책파일에 의존하며 누락 시 HTTP요청 중 프로세스종료. 시작시 설정검증·고정경로·
서비스 한번구성으로 후속 수정한다. 기존 native/ACL/capture/검색/운영/DR 완료조건은 남는다.


## 47. B4/B6 정책의 고정 경로·시작 검증과 배포 자산

JARVIS `4d8bdf0`, SB `aa7e76f`: [이번 수정5항목·잔여11우선과제](DASHBOARD-POLICY-STARTUP-2026-09-08.md).
46절에서 발견한 cwd 정책 누락에 따른 요청 중 서버 종료를 수정했다. 정책을 module-relative
자산으로 함께 게시하고 시작 시 한번 구성한다. 명시적 정책 오류는 listen 전 거부하며 CLI DB를
정리한다. 수정 전3실패→관련14/build10통과, 타입·린트·독립 검토·정규 격리 build 통과.
실제6프로세스에서 다른 cwd 정상 HTTP/CLI 및 잘못된 정책 거부를 확인했다. 기존 signer의
원격 승인 미준비와 native/ACL/자동capture/검색/운영/DR 미완료 조건은 유지한다.


## 48. B4/I1 후보 격리·차단의 승인과 V1 저장 집행

JARVIS `0c0508a`, SB `7e01e2b`: [수정6항목·실제 인수·다음 V2 경계](CANDIDATE-SUPPRESSION-WRITES-2026-09-08.md).
읽기 화면만 숨기고 classify replay/승인/outbox/직접 writer는 허용하던 문제를 수정했다.
실제 guard 누락4실패, 관련39·최종7·유효 adapter 집중6 통과(중복). 실제3프로세스에서
차단 이후 호출 증가0, 재시작 attempt0, HTTP200→404 및 준비된 승인 거부를 확인했다.
독립 검토로 발견한 correction confirmation 경합은 immediate transaction으로 수정했다.
P0 추가: V2 correction은 별도 preparation/materialization/beginDispatch/dedicatedAuthority를
사용해 V1 검사를 거치지 않는다. 이 경로와 자체 tombstone/원본 차단 구분을 다음에 보강한다.
원task→후보→provider record 계보 전까지 자동 collector 보류와 전체 미완료 조건을 유지한다.


## 49. V2 정정 차단 집행과 실제 계약에서 확인한 복구 보류

JARVIS `8a55ea9`, SB 도구 `db19ec5`: [이번 수정·검증·14개 후속 우선 목록](V2-CORRECTION-SUPPRESSION-2026-09-08.md).
후보 차단을 독립 V2 준비/전송/adapter 경로에 적용했다. 기존 spool을 보존하고 cursor claim과
beginDispatch를 immediate transaction으로 묶었다. 최종6파일22통과·타입/린트/격리build 및 실제
3프로세스에서 차단 후 추가 전송0·재시작 attempt0을 확인했다. provider는 합성 transport다.

P0 추가: 미전송 차단 lane을 건너뛰고 다음 요청에 이력을 실어 보내는 시제품은 실제 양쪽
validator가 EFFECT_TOMBSTONE_DELTA_INVALID로 거부했다. 해당 시제품의 합성 테스트 통과는
통합 성공 증거에서 제외했고 migration072·자동retirement·낮은checkpoint 예외를 철회했다.
기존 계약을 약화하지 않고 queued/tombstone/spool을 보류한다. 후속 정정·삭제의 자동복구는
양쪽 버전 계약·원본별 처분 증거를 갖춰 해결해야 한다. 새 OSS 코드/DB/Proxy는 도입하지 않았다.
전체 native/범위/원task계보/수집/검색/운영 완료 조건을 유지한다.


## 50. P0 자동 복구 선행: 본문 없는 정정 취소 의향

JARVIS `0ea62c8`, SB `e7efd62`: [구현·교차 런타임 검증·다음 6단계](CORRECTION-CANCELLATION-INTENT-2026-09-08.md).
기존 V2를 완화하지 않고 별도 signed intent library를 양쪽에 추가했다. 원본 content 없이
historical delegation/target/scope/tombstone과 현재 서명을 결합한다. 의향은 미수신/삭제 증거가
아니므로 아직 MCP나 전송/DB 상태 변경에 연결하지 않았다. 기존 AcceptedWriter fixture가 실제
V2 검증을 생략하던 문제도 수정하고 새로 서명된 혼합 delta 거부 회귀를 추가했다.

SB 기본947통과/2skip·최종집중30, JARVIS5파일41통과, 정적검사·lint·격리build통과.
실제 Node/Python16입력의 판정과5,775바이트 서명 일치. provider mutation0/운영사용없음.
취소seq1을 독립 적용·세대 전환한 뒤 V2seq2만 전송하는 방향으로 수신경합/alias영구차단/
실제억제세대/결과증거/cursor를 이어 구현한다. 자동복구 완료로 처리하지 않는다.
인계의 SB정본·JARVIS실행·선별OSS흡수와 기존 native/범위/계보/수집/검색/운영 목표를 유지한다.
