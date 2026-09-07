# 중앙 기억 완성 진행 원장

사용자 확정 목표: 기존 수정·개선·고도화 제안을 완성하고 기능/큰 단위마다 커밋한다. 문제가 될 기능·소스는 근거와 함께 보류하며 개발 완료는 실제 사용 검증으로 판정한다. 기존 범위를 이 원장에 유지하며 테스트 통과만으로 완료로 축소하지 않는다.

정본 계획: `IMPROVEMENT-BACKLOG-2026-09-07.md`, `OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md`.

최신 구현: [일반 여러 줄 기억 V3 인수](REMEMBER-V3-ACCEPTANCE-2026-09-08.md), 자비스 `1f7048a`. 명시적 새 후보/본문/MCP 계약으로 LF·CRLF·CR·탭 저장과 자비스 완료 소비를 연결했다. 기존 V1/V2/frozen schema4 유지. orphan 접수 시각 복구와 실행 전 파일 전체 digest 대조도 보강했다. 실제 CLI·MCP의 혼합 4개/일반 LF 64개 record 순환을 검증했고 운영 전환은 남는다.

종합 판정: [인계 병합 후 상세 분석](SHARED-MEMORY-COMPLETION-REVIEW-2026-09-08.md). 수정·개선·고도화 14개 실행 묶음을 기존 R/I/G에 대응한다. 이 문서의 V1 제약 재현은 유지하되 새 V3 후속 구현 상태는 위 인수 보고서를 우선한다.

최신 후속: [후보 CLI 접수·원문/DB 원자성](MEMORY-CANDIDATE-INTAKE-2026-09-08.md). 파일 접수부터 owner 확인·실제 MCP 저장/재조회까지 검증했으며 실제 task 결과 자동 수집·approved/no_data 본문 인계는 남는다.

이전 구현: [후보 화면·완료 상태 인수](JARVIS-MEMORY-CANDIDATE-UI-2026-09-08.md). 인계와 기존 24개 개선 항목을 유지하고 후보 검토·확인/거절·저장 명령 준비·진행 표시를 연결했다. 격리 실제 MCP에서 64개 민감 record 저장·두 클라이언트 재조회와 dashboard `stored=true`를 확인했다. 실제 입력 자동 수집, 앱별 수집/주입·범위와 운영 인수는 미완료다. 이전 코드 대조는 통합 계획 14절, 최신 변경은 15절을 따른다.

| 단위 | 범위 | 상태 | 완료 증거 |
|---|---|---|---|
| B0 | 기존 generation/provider 기반 + 운영 복구 + R1 입력 보존 | 완료 | 4da09b9; 520 passed, 2 skipped; Ruff·diff check 통과 |
| B1 | R2 public metadata / record 소비, R3 요청 기억 복원, R4 시간 계약 | 소스 구현·검증 완료, 운영 전환 미완료 | 공개 필드/ID·다중 record 소비·CAS 인용·시간 처리 수정. 실제 MCP→자비스 10개 기억 회수. 전체 업무 인수는 B4 |
| B2 | R5/R7/R9 검색 필터·결과 개수·읽기 세대 고정 | 소스 구현·검증 완료, 운영 미배포 | 필터·원장 read-only 투영, record 선택 뒤 limit, CLI pin. 동시 갱신 성능/복구는 B3에서 검증 |
| B3 | R6/I3 reader 복구·읽기 가용성 | 복구·LLM 준비 중 동시 조회 소스 검증, 운영 부하/잔여물 미완료 | 실제 reader/writer 강제 종료·PID 재사용·전환 정리, 두 writer·MCP/자비스 동시 조회 확인. 대표 p95·기존 잔여물 인수 남음 |
| B4 | I1/I7 공통 agent 접근·범위·자비스 전체 순환 | 후보 UI·명령 완료·서명 fence·일반 여러 줄 V3 소스 검증, 운영 전체 인수 미완료 | 원문 검토→승인 실행→저장 준비 브라우저 검증. V3 실제 CLI/MCP의 혼합 4개/일반 LF 64개 record·stored=true. 자동 업무 결과 수집·정정 UI·실제 앱·범위·운영 인수 남음 |
| B5 | G1/G3/G4/G6 기억 시간·문맥 예산·전달 이력·검증된 결과 | 미완료 | 정정·compaction·중복 전달·실패 사실 취급 |
| B6 | R8/I2/I4/I6/G5 readiness·운영 UI·배포·복구 | 준비 상태·검증 백업 선행 수정, 운영 인수 미완료 | 실제 서비스·검증 백업·독립 복원·운영 상태 일치 |
| B7 | I5/G2 부하·한국어 품질·100회 반복, I8 문서/모듈 검증 | 미완료 | 실측 평가·반복·용량·재현 설치 |
| B8 | R10 선택적 hybrid/관계 확장 | 조회 부작용·RRF 메타데이터 유실 수정, 활성화 보류 | cosine 출처/필터·세대 결합·삭제 수명 및 기준 검색 대비 이득 검증 필요 |

## 위험에 따른 보류

- 네 OSS 전체 서버·Proxy·전역 hook 동시 도입: 기존 기억 정본·인증·에이전트 정책과 중복/충돌하므로 보류. 기존 코드/작은 인터페이스 재사용으로 진행한다.
- 일반 graph DB/멀티모달 전체 도입: 현재 회수 결함을 해결하지 못하며 파생 데이터 삭제·정책·성능 검증 범위를 늘리므로 검색 평가 전에는 보류.
- LLM 요약만으로 실행 성공/승인된 사실 자동 승격: 자비스의 실행 증거 계약과 충돌하므로 구현하지 않는다. 검증 결과에 연결된 기억 후보·근거만 사용한다.
- 로컬 캐시를 에이전트별 기억 정본으로 운영: 공통 기억 일관성을 깨므로 보류. 캐시/전달 receipt는 재생성 가능한 운영 자료로 한정한다.
- owner-confirmed V1 correct 확장: 기존 승인 서명에 정정 target/prior가 포함되지 않아 보류. 신규 권한 소비는 remember에 한정하고, 정정은 기존 V2 target/delegation에 연결한다. 승인 후 대상 변경 거부와 실제 정정/재조회 검증이 재개 조건이다.

보류는 핵심 R1~R9나 실제 기억 저장·해석·복구를 회피하는 근거로 사용하지 않는다. 추가 보류에는 원인, 대신 제공할 동작, 재개 기준을 기록한다.

## 커밋/검증 기록

2026-09-07 KST 기준 작업 재개 시 HEAD `0ef3866`, 기존 대규모 staged provider 구현과 후속 수정이 미커밋 상태였다. 사용자의 변경을 보존한 스냅샷은 `/var/tmp/sb-goal-development-20260907/`에 저장했다. 별도 `phone-history/`, 임시 `2n`, `.bak-*` 파일은 이 개발 단위에서 제외한다.


### B1 진행 — 공개 응답·요청 출처 보강

- `fb47313`: MCP 공개 frontmatter를 기존 계약 필드에 투영. 내부 derivation_key와 원본 인용 span 보존.
- `77f3bad`: 같은 Git 경로로 검증되는 논리 ID/`wiki/` ID만 요청 ID와 일치시킴. 다른 페이지·잘못된 ID는 정상 ID로 위장하지 않음.
- 요청 remember는 원문 CAS와 8자리 hash 인용을 만들고 Vault를 통해 기록. 동일 후보 재처리는 동일 페이지, 다른 후보의 동일 원문은 출처별 페이지·공유 CAS로 보존.
- 정정/삭제에서 의도적으로 제거한 CAS를 참조하는 생존 문장은 해당 effect의 새 스냅샷에 연결. 원래부터 누락된 CAS를 정상 출처로 위장하지 않음.
- 검증: 전체 **527 passed, 2 skipped (119.23초)**, Ruff·diff check 통과. 추가 타입 경고는 수정했고 변경된 Vault/요청 복원 테스트는 **0 errors, 0 warnings**. 기준선의 다른 파일 경고 60개는 I8에 남음.
- 실프로세스: 독립된 managed generation의 단일 한국어 기억 → 실제 MCP → 수정하지 않은 자비스 transport/read adapter: **data 1 / current / evidence 1**. 내부 derivation_key와 논리 ID가 있는 실제 Vault 산출물을 사용.
- 운영 데이터 읽기 진단(소스 MCP만 교체): `운영 복구`는 conflicts, `업무`는 RECORD_IDENTITY_INVALID. 자비스 중복 키와 R4 시간 의미가 아직 차단 요인이다.
- 증거: `/var/tmp/sb-b1-20260907/`. 이번 후속 변경은 소스 검증이며 운영 release 전환은 아직 하지 않았다. 실제 자비스 candidate→outbox→settled 및 두 에이전트 앱 교차 사용은 미완료.

기존 병합 진행 상태는 기준선 커밋 `4da09b9`에서 마무리되었다(부모 `0ef3866`, `b5811d1`). 후속 작업 브랜치는 `codex/shared-memory-completion-20260907`이다. 무관한 미추적 자료는 계속 제외한다.


### B2 진행 — CLI 읽기 세대 고정

R9의 CLI status/search/sources/retention/metrics, doctor 조회, gc/migrate 미적용 조회, compile dry-run을 공통 read_config에 연결했다. reader pin이 반환한 generation root를 그대로 사용하며 별도 active 재조회는 제거했다. doctor --rebuild-ledger는 쓰기를 마친 뒤 읽기 pin을 얻으므로 잠금 중첩을 피한다. CLI 처리 실패에서도 reader lease가 해제되는지 검증했다.

집중 검사: CLI·runtime 관련 56개 통과. 테스트는 실제 generation의 등록 reader와 배타 잠금 차단을 확인하고 CLI 출력의 root가 고정된 generation인지 검사한다. 갱신 중 응답 지연 개선은 B3에 남으며, 이 커밋만으로 동시성 전체 완료를 선언하지 않는다.


### B2 검색 필터·최종 record 개수 검증

- Sealed 검색은 상태·수정 날짜·종류를 반영하고 기존 knowledge registry를 읽기 전용 snapshot으로 조회한다. 미등록 상태는 UNKNOWN, 승인/철회/후보 상태는 registry의 실제 값을 사용한다. 조회나 compile --state-report가 immutable 인덱스를 수정하지 않는다.
- `iter_lexical_hits`는 결과를 순차 처리한다. MCP schema 4는 title/heading만 일치하는 결과를 제외한 뒤 유효 record 개수에 limit를 적용한다. 페이지와 record의 중복 처리를 줄이고 구형 저장소의 128행 구간 이후도 이어서 탐색한다. Frozen wire schema와 도구 수는 변경하지 않았다.
- 검증: 집중 108개, 전체 **534 passed, 2 skipped (123.58초)**. Ruff·diff check 통과, 타입 **0 errors, 55 warnings**(기존 60개에서 감소).
- 운영 자료 실조회: 소스 CLI status가 generation root와 wiki 18/daily 2를 반환. `업무`의 9월 5일/wiki 필터 9건, 자료 없는 날짜 범위 0건. 테스트에서도 조회 전후 generation의 모든 파일 해시가 동일함을 확인했다.
- 증거: `/var/tmp/sb-b2-full-tests.log`, `/var/tmp/sb-b2-search-retest.log`, `/var/tmp/sb-b2-real-cli.json`, `/var/tmp/sb-b2-types-final.log`.
- 지식 상태 scope는 프로젝트 접근 권한 scope와 다르다. 프로젝트 범위는 B4, hybrid의 메타데이터/범위 보존은 B8에 계속 남는다. 이번 source MCP/CLI 검증으로 운영 배포나 자비스의 전체 기억 순환 완료를 주장하지 않는다.


### B3 진행 — 종료된 reader와 중단된 disposal 복구

- Linux boot ID + process starttime을 reader lease에 연결한다. 기존 reader_leases 열/호출 계약은 보존하고 별도 identity 테이블을 추가하여 구형 journal과 프로세스의 호환성을 유지한다.
- 실제 종료, zombie 또는 확인된 PID 재사용일 때만 lease를 정리한다. 생존 확인 실패·권한 오류·식별자가 없는 구형 live PID는 유지하고 오래되었다는 이유로 삭제하지 않는다. 실제 descriptor 검사는 기존대로 계속 적용한다.
- maintenance와 다음 mutation은 이미 전환된 활성 세대의 predecessor 정리를 먼저 마친다. 포인터 전환 후 실패한 정리를 건너뛰어 추가 세대를 만드는 경로를 막았다.
- 실제 spawn 프로세스가 pin을 잡은 상태에서 SIGKILL된 뒤, lease 잔여→정리→다음 generation 활성화→이전 디렉터리 폐기까지 검증했다. PID 재사용, 불확실한 생존 상태, 유지보수/다음 mutation의 재개도 검사한다.
- 운영 읽기 전용 관측: generation 디렉터리 7개, activation 상태 proved 11/activated 2. activated 2건의 generation 디렉터리는 이미 없어졌고 현재 active도 아니다. 이 과거 불일치와 잔여물은 최신 active 재개만으로 정리됐다고 간주하지 않는다. 백업/원장 대조 후 별도 복구해야 한다.
- I3의 LLM 실행 중 장시간 배타 잠금은 여전히 남아 있다. 이번 reader 복구가 조회 지연 개선을 의미하지 않는다. 운영 코드 배포는 아직 하지 않았다.

검증 결과: 전체 **540 passed, 2 skipped (127.40초)**, Ruff·diff check 통과, 타입 **0 errors, 55 warnings**. 새 process identity/reader recovery 관련 소스·테스트는 타입 오류·경고 0. 로그는 `/var/tmp/sb-b3-full-tests.log`, `/var/tmp/sb-b3-types-final.log`에 있다.


### B1 완료 보강 — 자비스 다중 기억 소비·시간 처리

- 자비스 `5c44b1f`: parser/집계 중복 키를 bound record ID/digest로 변경. page별 모든 검색 선택을 보존하며 한 번 읽고 각각 검증한다. 같은 출처의 여러 문장, 중복 선택, 같은 페이지의 잘못된 첫 선택이 정상 마지막 선택에 가려지는 경우를 검사했다.
- 자비스 `f9513d0`: bound record는 페이지 작성일만으로 하드 만료하지 않는다. 사실 구간 밖은 stale이며 즉시 응답 만료, 구간 안은 조회 시각에 설정 TTL을 더하되 명시적 종료일로 제한한다. strict identity/digest·generation·legacy 검사를 유지했다. 날짜 형식은 Python과 동일한 연도 1~9999의 24자 canonical UTC로 검증한다.
- Second Brain: 하루 일괄 만료를 제거하고 내부 명시적 기간을 검증·보존한다. 종료 미상은 열린 종료, 시작 미상은 열린 시작으로 표현한다. 이는 사실 검증일을 새로 추론하는 것이 아니다. 읽는 시각이나 합성 Git timestamp를 record ID에 넣지 않는다. 실제 sealed 두 세대의 날짜 없는 기록도 같은 ID를 유지한다.
- 독립 검토에서 지적한 page 선택 유실, 합성 commit 시각, 확장 연도·0년 불일치를 반영했다. `trust=untrusted`/`authority=none`과 target의 5분 만료는 유지한다.
- 최종 Python 전체 **548 passed, 2 skipped (123.92초)**; Ruff 통과; 타입 **0 errors, 55 warnings**. 새 시간 소스·테스트 타입 오류·경고 0. 자비스 기억 관련 단위 **244 passed / 26 files**, 변경 파일 ESLint 및 backend build 통과. 임시 복제 디렉터리의 중복 테스트는 최종 수치에서 제외했다.
- 실제 프로세스: 소스 MCP와 빌드한 자비스 transport/read adapter로 운영 자료를 읽어 `운영 복구` current 1개, `업무` current 10개. 소비자 시계를 현재/다음 날/35일 뒤로 바꿔도 같은 record ID 10개, bounded expiry, untrusted를 확인했다. 사용자 내용을 테스트 fixture로 복제하지 않았다.
- 증거: `/var/tmp/sb-time-final-tests.log`, `/var/tmp/sb-time-final-types.log`, `/var/tmp/jarvis-memory-time-final-tests.log`, `/var/tmp/jarvis-memory-time-build.log`, `/var/tmp/jarvis-memory-time-probe.jsonl`, `/var/tmp/jarvis-memory-future-probe.jsonl`.

R4는 기존 기록의 digest를 바꾸므로 실행 파일만 바꾸는 배포는 하지 않는다. [시간 계약](MEMORY-TIME-CONTRACT-2026-09-07.md)의 유지보수 경계에서 새 provider release 세대와 실행 파일을 함께 전환하고 기존 target은 재조회해야 한다. 운영 release/서비스/active 포인터는 이번에 전환하지 않았다. 현재·미래 시계 프로브는 읽기 검증이며 35일 실운영, 자비스 candidate/outbox/settled 순환, 두 에이전트 앱 공유 완료의 증거가 아니다. B4~B8 및 I3 지연·B3 과거 잔여물은 계속 진행 대상이다.


### B4 진행 — 실제 MCP/outbox 순환과 재사용

자비스 `471cab3`에서 세션 전체 generation 고정을 public 조회 단위로 분리하고 schema4 recentChanges의 generation 유실을 수정했다. 수정 전 실제 격리 순환은 settled 이후 reader 재사용에서 실패했다. 수정 후 pending→proved→settled→같은 reader current 1개, 독립 두 번째 MCP 프로세스의 동일 record 회수, replayed=true→apply idle→outbox 추가 dispatch 0을 확인했다.

재현 가능한 `scripts/jarvis-memory-acceptance.mjs`와 격리 provider fixture를 추가했다. 자비스의 합성 검증 결과·서명 fixture를 사용하며, 하네스가 expected selector를 만들고 apply/reconcile을 호출한다. 따라서 실제 업무 검증, 운영 자동 연결, 실제 Codex/Claude 앱 공유, 여러 줄 입력 완료와 구분한다.

검증: 자비스 관련 단위 **247 passed / 26 files**, ESLint·backend build 통과, 독립 코드 검토 완료. 새 Python fixture Ruff·타입 오류/경고 0, Node 구문 검사 통과. 상세 관측 및 새로 확인한 필수 잔여 I1-a~e는 [순환 인수 보고서](JARVIS-MEMORY-CYCLE-ACCEPTANCE-2026-09-07.md)에 있다. 핵심 잔여는 운영 outbox 생성·승인 원문 보존·selector 생성·여러 줄 판정·비동기 reconciliation이다. 운영 배포나 권한 우회는 수행하지 않았다.


### B4 진행 — 2026-09-08 승인 원문 수명과 종료 후 재확인

자비스 `64b255b`: 승인/거절 중 원문 삭제를 제거하고 committed terminal 상태에서만 digest를 검증해 정리한다. 진행 중 원문은 confirmation 기한만으로 삭제하지 않는다. 원문 정리 뒤 동일 명령의 결과 재확인이 가능하며, 정리 실패를 이미 완료된 저장의 실패로 바꾸지 않는다. 다음 cycle에서 정리를 재시도한다. 실제 분류→승인에서 드러난 후보 키/provider 키 혼용도 새 dispatch 생성에서 수정했다.

집중 검증 **91 passed / 37 files**, 변경 파일 ESLint·backend build 통과, 독립 검토 완료. 격리 실제 MCP→outbox→proved→settled→두 클라이언트 재조회 순환에서 원문 파일 0개와 terminal replay settled, 중복 dispatch 0을 확인했다. 상세 로그와 범위는 [인수 보고서 후속](JARVIS-MEMORY-CYCLE-ACCEPTANCE-2026-09-07.md)에 기록했다.

I1-b는 전체 승인 쓰기까지 완료가 아니다. 승인된 inference의 authority claim/receipt 연결, 바깥 DB rollback 후 dispatch metadata 잔여물 재승인 복구가 남는다. 실제 runtime 생성·selector·여러 줄·reconciliation 및 cleanup 오류 표시도 남아 있다. B3 지연/과거 잔여물, B5~B8 전체 범위와 운영 전환은 계속 미완료다.

### B4 진행 — owner-confirmed remember 권한 연결

자비스 `d553327`: 이후 owner confirmation에서 발생한 실제 결정·서명·개인 redemption을 검사하여 remember를 허용한다. 원문·주제·정책 값과 후보를 일치시키고 실제 receipt 만료를 넘지 않는다. 기존 auto-staged 경로의 내용 불일치도 거부한다. inference 분류는 유지한다. V1 correct는 승인과 prior 결합이 부족하므로 신규 경로에서 허용하지 않고 기존 V2 연결로 진행한다.

집중 **91 passed / 36 files**, 타입 보정 후 해당 경로 **7 passed**, ESLint·backend build·독립 검토 완료. 실제 분류→합성 owner 승인→별도 MCP→provider proved→outbox settled→두 번째 클라이언트 동일 기억 회수까지 통과했다. 기존 verified fixture 순환도 통과했다. 상세 명령·증거·보류 사유는 [인수 보고서](JARVIS-MEMORY-CYCLE-ACCEPTANCE-2026-09-07.md)에 있다.

원문/권한 경로의 소스 검증과 runtime 배포를 구분한다. 실제 서비스 자동 outbox 생성, selector, 여러 줄, reconciliation, project/user/agent 범위, rollback metadata 복구 및 B3/B5~B8의 미완료 범위는 유지한다.

### B4 진행 — 전체 record 검증·민감도·완료 관측 예산

자비스 `c7c5182`: 영속 publication/권한에서 expected_artifact 명령을 구성하며, canonical remember 결과는 원문 전체와 모든 record의 개수·순서·출처·span·세대·민감도를 대응해 판정한다. Second Brain은 요청 민감도를 Vault에 보존하고 읽을 수 없는 record 묶음을 접수/CAS 쓰기 전에 거부한다. 기본 예산은 유지하고 schema4에 명시적 record-set-v1 완료 관측 프로필을 추가했다.

전체 Python **556 passed, 2 skipped (124.09초)**, 자비스 집중 **287 passed / 32 files (36.09초)**, Ruff·변경 ESLint·backend build·Node 구문 검사 통과. 변경 Python 타입 오류/경고 0, 자비스 독립 검토 완료. 실제 격리 MCP에서 4개 반복/공백/footnote 및 64개 record의 일반·sensitive 입력이 proved→settled→두 클라이언트 회수, replay/추가 dispatch 0, terminal 원문 정리를 통과했다.

기본 64KB 예산으로 64개를 읽으면 AGGREGATE_OVERSIZE로 reconciling에 남고 원문은 유지된다. 운영 완료 reader에 새 프로필을 명시 주입해야 한다. 일반 LF는 V1에서 여전히 거부되므로 일상 여러 줄 입력 완료가 아니다. 상세 재현과 한계는 [결과 대응 계약](REMEMBER-ARTIFACT-CONTRACT-2026-09-08.md)에 기록했다. 운영 자동 구성·주기적 재확인·승인 rollback metadata 복구·V2 정정·프로젝트 범위·실제 앱 검증과 B3/B5~B8은 미완료다.

### B4 진행 — 승인 rollback metadata 복구

자비스 `316b8f2`: 승인 event/바깥 DB rollback 뒤 남은 권한 없는 dispatch 파일을 같은 원문·후보인지 검사하고 새 receipt로 재발행한다. DB writer lock 안에서 영속 receipt/decision/publication/outbox를 확인하며, 이미 확정됐거나 변경·손상된 파일은 보존한다. 동일 receipt 재시도와 원문 보존 규칙은 유지한다.

변경 전 두 경로 replay conflict 재현, 변경 후 최종 회귀 **92 passed / 35 files (40.47초)**, 변경 ESLint·backend build·독립 검토 통과. 실제 격리 MCP에서 rollback→새 승인→민감 기억 64개 proved/settled→두 클라이언트 회수·추가 dispatch 0·원문 정리까지 검증했다. 재현 명령과 한계는 [순환 인수 보고서](JARVIS-MEMORY-CYCLE-ACCEPTANCE-2026-09-07.md)의 마지막 절에 있다.

I1-b의 이 소스 결함은 수정됐다. 운영 실행기 outbox 주입과 주기적 완료 확인은 여전히 없으며 I1-a/c/e를 이어간다. B3 지연/과거 잔여물, 일반 LF·V2 정정·프로젝트 범위·실제 앱, B5~B8과 운영 배포/복원 검증은 계속 미완료다.

### B4 진행 — CLI/dashboard 실행기와 주기 완료 확인 연결

자비스 `a680fd5`: 공통 production outbox factory를 CLI control.execute와 dashboard executor에 연결했다. stage-dispatch는 예상 결과를 계산해 기존 승인용 명령을 구성한다. memory outbox --once/list로 처리·상태 확인이 가능하며 dashboard 기존 interval이 bounded cycle을 실행한다. 완료 reader의 예산/read fence, 공통 spool root, transport 소유권을 보존한다. HTTP 실행과 tick을 drain한 뒤 DB를 닫고 상태 변경을 명시 통지한다.

회귀 **100 passed / 39 files**, 추가 tick/SSE 검사 **11 passed / 4 files**(일부 중복), 변경 ESLint·backend build·독립 검토 통과. 실제 격리 MCP에 CLI execute 경로로 민감 기억 64개를 보내고 다음 CLI cycle에서 settled와 독립 클라이언트 회수, 재전송 중복 0을 확인했다. Python 소스는 변경하지 않았다.

실측에서 control command는 outbox settled 뒤에도 uncertain으로 남는다. 영수증 기반 최종 상태 반영을 다음 필수 수정으로 지정했다. 기본 운영 signed-fence 구성, 후보/publication/UI 전체 흐름, 배포·실제 앱/범위 및 B3/B5~B8은 계속 미완료다. 상세 재현·변경·한계는 [기억 실행기 연결 보고서](JARVIS-MEMORY-RUNTIME-2026-09-08.md)를 따른다.

### B4 진행 — 기억 완료 증거에서 원래 명령 최종 상태 복구

자비스 `20c8936`: 앞 절의 uncertain 잔존 결함을 후속 수정했다. 기존 command/receipt/redemption/fence와 dispatch·observation·settlement 증거를 검증하고 uncertain 또는 lease 만료 claimed를 completed/failed로 반영한다. 취소/철회와 과거 uncertain 이력을 보존하며 재전송하지 않는다. 오류 작업을 지나가는 영속 순환 커서와 원자적 상태/effect/event 기록을 추가했다. cursor 저장 실패가 이미 성공한 다른 실행을 failed로 바꾸지 않는 회귀도 포함한다.

최종 회귀 **160 passed / 52 files (85.42초)**, backend build·변경 ESLint·독립 재검토 통과. 실제 격리 MCP·CLI API에서 민감 기억 64개가 proved→outbox settled→control completed로 연결됐다. 두 클라이언트 current, 추가 dispatch 0, review 원문 0개, cleanup/control 오류 없음. 소스·검증·잔여 우선순위는 [명령 완료 연결 보고서](MEMORY-CONTROL-COMPLETION-2026-09-08.md)를 따른다. 운영 배포·서명 fence 기본 구성·실제 앱/범위·B3/B5~B8의 전체 완료로 확대하지 않는다.

### B4 진행 — 삭제 이후 기본 서명 조회와 재저장

기본 CLI/dashboard가 기존 자비스 등록 키·provider identity·현재 DB 삭제 원장으로 read fence를 생성하도록 연결했다. 키 만료/철회는 매 조회 확인하고 DB별 outbox를 분리한다. 실제 삭제에서 발견한 SB 빈 `sources: []` 공개 응답도 기존 scalar로 정규화했다. frozen 계약과 승인 구조는 유지한다.

자비스 관련 회귀 **149 passed / 26 files**, Python 공개 응답·MCP 계약·삭제/복원 **18 passed**, backend build·lint·독립 검토 통과. 격리 실제 MCP에서 삭제 proved/sequence 1, 무서명·과거 fence 거부, 삭제 record 0, 이후 민감 record 64개 저장→control completed→두 클라이언트 회수 성공. 상세 설정과 증거는 [삭제 이후 조회 보고서](MEMORY-READ-FENCE-INTEGRATION-2026-09-08.md). 운영 구성·배포, 실제 후보/UI·앱별 수집/주입·접근 범위, 일반 LF/V2 정정, B3/B5~B8은 남는다.

### B3 진행 — LLM 준비 중 조회와 writer/삭제 경계

세대 writer 전용 mutex를 유지한 채 sealed 부모에서 successor를 준비하는 구간만 reader와 공유한다. 전환/폐기 전에는 EX로 복구하고 실제 부모와 삭제 원장을 다시 검사한다. MCP 조회가 유지보수의 writer 잠금에 재차 막히던 경로도 idle 조건의 정리로 바꿨다. 만료 export 상태는 cleanup이 미뤄져도 available로 서명하지 않는다.

별도 pipeline process를 준비 중 유지한 상태에서 실제 stdio MCP 검색·페이지·상태 조회, 두 writer의 순서/내용 보존, reader pin 보호, writer kill 복구, 삭제 접수 시 오래된 조회/전환 거부를 검증했다. 실제 자비스 CLI 완료 cycle과 두 MCP 클라이언트의 64개 민감 record 회수는 약 **1.394초**, control completed/outbox settled, 추가 dispatch 0, cleanup/control 오류 없음이었다. `/var/tmp/sb-jarvis-concurrent-compile-verified-acceptance.log`.

검증 중 발견한 첫 기억→export의 필수 log 누락도 Vault 초기화로 수정하고 raw/.sb의 Git 제외를 seal 경계에서 보장했다. 기존 제외 취소 규칙보다 강제 규칙을 뒤에 배치하며 CAS 원문은 보존한다. 최종 전체 **564 passed / 2 skipped, 138.84초**, 독립 검토 지적 두 건 수정 후 추가 actionable 없음, 변경 타입 오류/경고 0, 전체 Ruff·하네스 구문 검사 통과. 세부 한계는 [갱신 중 조회 보고서](GENERATION-READ-CONCURRENCY-2026-09-08.md).

운영 p95·부하 인수, 과거 `.staging`/미활성 세대의 원장 기반 복구는 남는다. 임시 디렉터리 일괄 삭제를 보류했고 자비스 signed export status 소비 미구현도 I1 후속으로 기록했다. 운영 서비스·release/active generation·push는 변경하지 않았다.


### B4 진행 — 후보 검토 화면과 실제 저장 진행 상태

자비스 `c4c5c98`: 기억 후보 상세를 영속 원문·출처·정책 digest에 결합하고 검토한 내용으로 확인/거절 명령을 준비한다. 승인된 후보의 저장 명령 준비와 control/outbox 진행 API·화면을 연결했다. remember 확인 실행기의 잘못된 correct 분기와 Overview 동시 DB 변경 오판도 재현·수정했다. 기존 owner 승인·outbox·SB 계약을 재사용한다.

최종 커밋 기준 `49446db`와 이 단위 소스를 격리하여 build 및 후보/HTTP/동시성 15개 통과. frontend 전체 143개, 관련 회귀 72개·투영 26개·최종 Overview 13개는 일부 중복으로 별도 기록한다. Playwright 1440/375px의 검토→승인 실행→저장 pending→새로고침 유지, 콘솔 오류/serious·critical 접근성 위반/가로 넘침 0. 실제 MCP/CLI 인수는 64개 민감 record·두 클라이언트 current·control completed/outbox settled에 dashboard stored=true까지 확인했다. 독립 재검토 추가 지적 없음.

상세 증거와 잔여는 [인수 보고서](JARVIS-MEMORY-CANDIDATE-UI-2026-09-08.md). 실제 업무 후보 수집·private 후보 UI·일반 LF/V2 정정·앱별 공유/주입·접근 범위·운영 전환 및 B5~B8은 남는다. 서비스·운영 세대·push는 변경하지 않았다.


### B4 진행 — 제품 후보 접수와 원문/DB 시간 일치

자비스 `b89dab6`: `memory classify <input.json> <policy.json>` 제품 진입점과 기존 owner 확인/저장 흐름을 연결했다. 실제 시계에서 원문/DB 해시가 달라지던 결함, commit 전 남은 원문의 재시도 충돌, 부적격 원문 발행과 만료 감사행 제약 충돌을 수정했다. 동일 원문만 제한적으로 복구하며 새 승인 구조나 임의 자동 승인을 만들지 않는다.

CLI 접수에서 시작한 실제 MCP 인수는 민감 기억 64개·두 클라이언트 current·completed/settled/dashboard stored=true, 중복 추가 dispatch 0을 확인했다. 실제 시계의 CLI subprocess 재시도/원문 검토도 통과했다. 관련 37개 및 추가 회귀 123개, backend build·lint·독립 재검토 통과. [보고서](MEMORY-CANDIDATE-INTAKE-2026-09-08.md).

이번 중 확정된 자비스 task completion `7129b9d`와 기억 verifier authority 연결을 다음에 대조한다. 바로 approved 또는 no_data 후보의 본문 인계, 일반 LF/V2·실제 앱/범위 및 B5~B8과 운영 인수는 남는다.

### B4 보류 판정·B8 선행 수정 — 원본 차단 전파와 벡터 읽기

task completion 수집 초안은 task_id 차단 누락과 원본 차단의 파생 후보/저장 전파 부재를 확인해 제품에 반영하지 않았다. 자비스 `73d59df`에 수집 전/후·전송 중·저장/복원 후까지의 재개 조건을 기록했다. 기존 classify·검토·owner 확인·outbox는 유지한다.

SB query_cosine의 조회 중 DROP/CREATE를 readonly SQLite CTE로 바꾸고 RRF가 출처/상태 필드를 보존하도록 수정했다. 없는 DB 생성, 모델/revision 불일치 허용, 제어문자 원문 손상과 잘못된 거리의 완전 일치 오판도 수정했다. 수정 전 6건 실패로 재현했고 실제 SQLite 동시 조회 전후 DB 불변·readonly 쓰기 거부를 검증했다.

표준 전체 **566 passed, 2 skipped (138.94초)**, optional 포함 집중 **32 passed, 1 skipped (2.28초)**이며 두 실행은 일부 중복이다. Ruff·diff check 통과, 변경 소스 타입 오류/경고 0. [상세 보고서](HYBRID-READONLY-2026-09-08.md). 실제 모델 품질·cosine 전용 출처/필터·세대/삭제 수명 결합과 hybrid 활성화는 남는다. B4~B8 전체나 운영 전환 완료를 의미하지 않는다.

### B4 진행 — V2 정정의 줄바꿈·인용·완료 관측

실제 요청에서 `PROVIDER_ARTIFACT_INVALID`로 reconciling에 남던 CRLF 정정과 중간 문장 인용 누락을 수정했다. LF/CRLF·빈 줄을 보존하고 각 문장에 기존 citation을 연결한 뒤 effect snapshot으로 재결합한다. 사용자 인용 구문은 문자로 escape한다. 출력 record 수/길이를 대상 쓰기 전에 검증하며 raw content digest와 frozen V1/V2/MCP 필드는 유지한다.

격리 실제 MCP에서 새 문장 4개를 두 자비스 소비자가 current로 회수했고 내용 digest·effect 출처가 모두 일치했다. 자비스 서명 proof/관측 검증기 통과, 이전 기억 0건, replay=true/추가 적용 idle, 변경 원문과 과거 fence 거부를 확인했다. [상세 인수 및 한계](CORRECTION-RENDERING-2026-09-08.md).

전체 **571 passed, 2 skipped (157.58초)**, 관련 집중 **22 passed (20.48초)**이며 일부 중복이다. Ruff·Node 구문·diff check 통과, 변경 소스 타입 오류/경고 0.

V1 신규 remember의 일반 줄바꿈, 자비스 정정 UI/사용자 승인/production saga/control 완료의 전체 인수와 B4~B8 운영 완료는 여전히 남는다. 자비스 제품 소스·서비스·운영 세대·push는 변경하지 않았다.


### B4 진행 — 자비스 V2 정정 명령 완료와 중단 복구

자비스 `4721358`: 기존 correction saga의 settled와 control 완료 사이 commit 간격, 만료/시각 재사용, compaction 이후 명령 원형 소실, settled 주기 복구 누락을 수정했다. 원문 없는 immutable binding과 원 승인·전송 fence·서명 provider proof·동일 lane purge를 대조한 뒤 원장/완료/effect/event를 함께 commit한다. 이미 compaction이 끝났으면 provider가 중단돼도 로컬 증거로 복구한다.

새 회귀 11개를 포함한 관련 **34 passed / 9 files (50.15초)**, backend build·변경 lint·독립 재검토 통과. 격리 실제 SB MCP에서 후보 확인→승인 dispatch→정정 proved→최종 event 실패→20분 후 control completed, 전송/compaction 각 1회, 복구 중 provider 추가 관측 0회를 검증했다. 두 reader의 같은 정정 record 4개·내용/출처 digest 일치와 이전 기억 0개를 확인했다. [수정 내역·검증 한계·후속 목록](CORRECTION-CONTROL-COMPLETION-2026-09-08.md).

이 검증은 합성 owner 서명을 쓰는 실제 backend 순환이다. 정정 UI/실제 사용자 승인 화면, 실제 앱별 수집·주입, V1 일반 LF, 접근 범위, task 원본 차단 전파와 운영 인수는 남는다. 운영 DB migration·배포·서비스 재시작·push는 수행하지 않았다.


### B6 진행 — 검증 백업과 운영 준비 상태

R8/I6의 mtime 기반 백업 정상 오판, 오래된 실행·정체 요청·최근 실패·손상 journal 누락을 수정했다. CLI backup은 격리 복원 검증 후 receipt를 남기고 기존 archive는 verify-backup으로 검사한다. 원 저장소/provider·생성 시각·파일 identity·삭제 sequence/root를 확인하며, 관리형 검증은 기존 generation/request 잠금을 유지하고 오래된 삭제 이력의 archive를 복원 전에 거부한다.

표준 전체 **591 passed / 2 skipped (158.89초)**, 관련 집중 **36 passed (13.36초)**. 전체 Ruff·신규 모듈/CLI 타입 오류·경고 0, 실제 CLI/HTTP에서 health 200과 ready 503→200→503 분리, 손상 verify exit 1, 임시 복원 잔여 0, 관리형 backup origin/삭제 이력 보존을 확인했다. [상세 동작·설정·검증 및 한계](READINESS-VERIFICATION-2026-09-08.md).

실제 운영 백업 검사·배포·runtime 재기동/활성화 인수, 자비스 adapter 인수 receipt의 readiness 결합, 대용량 검증 잠금/공간 최적화는 남는다. 출처가 없는 과거 백업과 오래된 삭제 이력을 추정으로 정상 승격하지 않는다. 운영 서비스·세대·push는 변경하지 않았다.
