# 중앙 기억 완성 진행 원장

사용자 확정 목표: 기존 수정·개선·고도화 제안을 완성하고 기능/큰 단위마다 커밋한다. 문제가 될 기능·소스는 근거와 함께 보류하며 개발 완료는 실제 사용 검증으로 판정한다. 기존 범위를 이 원장에 유지하며 테스트 통과만으로 완료로 축소하지 않는다.

정본 계획: `IMPROVEMENT-BACKLOG-2026-09-07.md`, `OSS-ABSORPTION-INTEGRATION-PLAN-2026-09-07.md`.

| 단위 | 범위 | 상태 | 완료 증거 |
|---|---|---|---|
| B0 | 기존 generation/provider 기반 + 운영 복구 + R1 입력 보존 | 완료 | 4da09b9; 520 passed, 2 skipped; Ruff·diff check 통과 |
| B1 | R2 public metadata / record 소비, R3 요청 기억 복원, R4 시간 계약 | 진행 중 | R2 공개 필드/ID 수정, R3 CAS·정정 후 인용 보강. R4 및 자비스 중복 판정 미완료 |
| B2 | R5/R7/R9 검색 필터·결과 개수·읽기 세대 고정 | 소스 구현·검증 완료, 운영 미배포 | 필터·원장 read-only 투영, record 선택 뒤 limit, CLI pin. 동시 갱신 성능/복구는 B3에서 검증 |
| B3 | R6/I3 reader 복구·읽기 가용성 | 미완료 | 강제 종료·전환 중 읽기·deadline 내 응답 |
| B4 | I1/I7 공통 agent 접근·범위·자비스 전체 순환 | 미완료 | 독립 클라이언트 A 저장/B 조회, 요청 ID/receipt/record 연결, 범위 검사 |
| B5 | G1/G3/G4/G6 기억 시간·문맥 예산·전달 이력·검증된 결과 | 미완료 | 정정·compaction·중복 전달·실패 사실 취급 |
| B6 | R8/I2/I4/I6/G5 readiness·운영 UI·배포·복구 | 미완료 | 실제 서비스·검증 백업·독립 복원·운영 상태 일치 |
| B7 | I5/G2 부하·한국어 품질·100회 반복, I8 문서/모듈 검증 | 미완료 | 실측 평가·반복·용량·재현 설치 |
| B8 | R10 선택적 hybrid/관계 확장 | 판단 필요 | sealed 읽기·정책·출처 보존과 기준 검색 대비 이득 |

## 위험에 따른 보류

- 네 OSS 전체 서버·Proxy·전역 hook 동시 도입: 기존 기억 정본·인증·에이전트 정책과 중복/충돌하므로 보류. 기존 코드/작은 인터페이스 재사용으로 진행한다.
- 일반 graph DB/멀티모달 전체 도입: 현재 회수 결함을 해결하지 못하며 파생 데이터 삭제·정책·성능 검증 범위를 늘리므로 검색 평가 전에는 보류.
- LLM 요약만으로 실행 성공/승인된 사실 자동 승격: 자비스의 실행 증거 계약과 충돌하므로 구현하지 않는다. 검증 결과에 연결된 기억 후보·근거만 사용한다.
- 로컬 캐시를 에이전트별 기억 정본으로 운영: 공통 기억 일관성을 깨므로 보류. 캐시/전달 receipt는 재생성 가능한 운영 자료로 한정한다.

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
