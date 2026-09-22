# JM / BLRO Core5 메모리 통합 개발계획

작성일: 2026-09-21  
기준 문서: `JM_BLRO_Core5_Development_Plan_20260920.html`  
대상: Orca-JARVIS, second-brain-app, phone-history

## 0. 문서 적용 범위

첨부된 Core5 계획서의 방향과 지시사항은 다음과 같이 유지한다.

- 기존 시스템을 정본으로 유지하고 필요한 기능만 선별 통합한다.
- JARVIS는 요청·승인·실행 조정을 소유한다.
- Second Brain은 원본·출처·검색·정정·삭제를 소유한다.
- Phone History는 수집·redaction·이벤트 전송을 소유한다.
- 새 기억 데이터베이스를 만들지 않는다.
- 운영 전환·실제 데이터 삭제·복원·배포는 오너 승인 후 수행한다.
- 합성 fixture 결과를 운영 완료로 확대하지 않는다.

이 문서는 첨부 계획서의 지시를 대체하지 않는다. 사용자 요청에 따라 그 계획서에 **Second Brain 현재 상태, Phone History 연동, JARVIS 실제 종단 검증, 운영 전환 순서**를 추가한 실행 계획이다.

## 1. 현재 기준 상태

| 영역 | 현재 상태 | 판정 |
|---|---|---|
| Second Brain | CLI·MCP·웹 저장·검색·배치·백업·복원 운영 확인. `/ready` 정상 | 기본 단일 사용자 사용 가능 |
| Second Brain 철회 | 소스와 집중 테스트에는 구현됨. 운영 설치본에는 아직 미반영 | 배포 전 |
| Phone History | `SecondBrainSink.export()`는 직접 inbox 적재만 수행. `retract()` 없음 | 단방향 연동 |
| JARVIS | 메모리 계약·provider adapter·승인 구조는 존재. 실제 운영 read/write 종단 증거 부족 | 통합 검증 필요 |
| 운영 안정성 | 웹 서비스가 OOM으로 재시작된 기록 있음 | 안정성 보완 필요 |
| 저장소 기준선 | 세 프로젝트 모두 수정·미추적 파일이 존재. Second Brain 로컬 branch는 원격보다 뒤처짐 | G0에서 기준선 고정 |

## 2. 개발 완료 조건

최종 완료는 다음 네 조건을 모두 만족할 때만 선언한다.

1. JARVIS가 인증된 요청으로 Second Brain에 기억을 쓰고 완료 receipt를 받는다.
2. 새 JARVIS 세션 또는 다른 허가된 에이전트가 같은 기억을 검색·읽는다.
3. Phone History 업로드를 철회하면 receipt, 검색 제거, CAS tombstone, 재유입 차단이 모두 확인된다.
4. 새 release의 source commit·wheel hash·운영 서비스·테스트 결과가 서로 일치한다.

## 3. 개발 순서

### G0 — 세 프로젝트 기준선 고정

**목표:** 현재 구현과 운영 설치본을 혼동하지 않도록 기준을 고정한다.

작업:

- JARVIS, Second Brain, Phone History 각각의 HEAD·branch·dirty 목록을 기록한다.
- 운영 설치본의 release ID, source commit, wheel hash, 활성 서비스와 포트를 기록한다.
- 실제 활성 MCP profile, issuer, provider 주소, 인증 환경변수를 이름만 기록한다. 비밀값은 기록하지 않는다.
- 첨부 계획서의 기존 T01/T02 기준 시험을 먼저 실행한다.
- 미커밋 변경과 미추적 산출물을 제품 변경·검토 증거·임시 파일로 분리한다.

통과 조건:

- 세 저장소의 기준 commit과 운영 설치본이 문서화됨
- 기준 불일치와 미확인 항목이 `BLOCKED` 또는 `PENDING`으로 명시됨
- 사용자 변경을 삭제하지 않음

### G1 — 공통 계약과 책임 고정

**선행:** G0  
**목표:** 세 프로젝트가 같은 ID와 상태 의미를 사용하게 한다.

고정할 계약:

- `operation_id`: 논리 작업 ID
- `attempt_id`: 실행 시도 ID
- `upload_id`: Phone History 업로드 ID
- `receipt_id`: Second Brain 처리·철회 결과 ID
- `request_id`: JARVIS 요청 ID
- `fence`와 deletion high-water: 오래된 writer와 삭제 자료 재유입 차단

책임:

- JARVIS: 요청, 승인, 실행 상태, 재시도, 대사
- Second Brain: 원본, CAS, 검색, citation, 정정, 삭제, receipt
- Phone History: 이벤트 식별, redaction, 업로드 요청, 업로드·철회 상태 표시

통과 조건:

- Node/Python golden fixture가 동일한 필드와 digest를 해석함
- 어느 시스템도 다른 시스템의 DB를 직접 수정하지 않음

### G2 — Second Brain 운영 release 준비

**선행:** G1  
**목표:** 현재 소스의 철회 기능을 운영 가능한 release로 만든다.

작업:

- `sb/uploads.py`, `sb/web.py`, CAS, 검색 인덱스 변경을 하나의 검토 가능한 commit으로 고정한다.
- Phone History 연동에 필요한 `file_retract` capability를 계약에 반영한다.
- `POST /api/uploads/retract`와 `GET /api/retracts/{receipt_id}`를 인증·idempotency·오류 응답까지 고정한다.
- staged inbox 삭제, CAS tombstone, 검색 제거, page forget, 재업로드 차단을 하나의 sandbox E2E로 검증한다.
- 새 wheel과 운영 release를 만들고 manifest의 source commit과 artifact hash를 대조한다.

통과 조건:

- 운영 `/api/capabilities`에 철회 기능이 실제로 표시됨
- 동일 upload ID의 반복 철회가 같은 receipt를 반환함
- 서비스 재시작 후 receipt와 tombstone이 유지됨

### G3 — Phone History 양방향 연동

**선행:** G2  
**목표:** Phone History 이벤트의 저장과 철회를 완성한다.

작업:

- `SecondBrainSink.export()`가 upload ID와 content digest를 보존하도록 확장한다.
- `SecondBrainSink.retract(upload_id)`를 구현한다.
- HTTP API 방식이면 base URL과 인증 변수(`SB_WEB_TOKEN` 등)를 설정 계약에 명시한다.
- 직접 Vault 방식이면 동일 writer·lock·receipt 규칙을 사용하고 HTTP 경로와 의미를 다르게 만들지 않는다.
- 철회 결과를 `deleted`, `indexed`, `restored`, `receipt_id`로 검증한다.
- 네트워크 실패·404·receipt 지연 시 이벤트를 삭제하지 않고 pending 상태로 보존한다.

통과 조건:

- Phone History 테스트에서 upload → retract → receipt 조회가 재현됨
- 삭제 후 검색 결과 0건, CAS `exists=False`, tombstone 존재가 확인됨
- 철회된 upload ID의 재유입이 거부됨

### G4 — JARVIS 실제 기억 종단

**선행:** G2, G1  
**목표:** JARVIS가 Second Brain을 실제 공통 기억 저장소로 사용하는 것을 증명한다.

작업:

- 실제 활성 provider 주소·MCP profile·issuer·read/write 권한을 확인한다.
- JARVIS A 세션에서 기억 쓰기 요청을 발행한다.
- Second Brain request journal, 처리 상태, 완료 receipt를 확인한다.
- JARVIS B 또는 새 세션에서 동일 기억을 검색·읽는다.
- 권한이 다른 요청·만료된 fence·삭제 후 과거 claim·캐시 재사용을 거부하는지 확인한다.
- JARVIS가 `accepted`를 `completed`로 잘못 표시하지 않도록 상태를 분리한다.

통과 조건:

- 실제 인증 경로에서 write → receipt → new session read가 모두 성공
- read/write 권한이 없는 요청은 fail-closed
- 합성 fixture 결과와 실제 provider 결과가 별도 기록됨

### G5 — 운영 안정성과 전체 품질 게이트

**선행:** G2~G4  
**목표:** 기능이 실제 운영에서 지속되는지 확인한다.

작업:

- Second Brain 웹 서비스 OOM 원인을 재현·분석하고 메모리 상한 또는 처리량 제한을 적용한다.
- refresh·backup·web 동시 실행을 조정한다.
- `/ready`가 오래된 실행·실패·백업 미검증을 정확히 표시하는지 확인한다.
- 전체 pytest, Ruff, basedpyright, build를 같은 source commit에서 실행한다.
- JARVIS Vitest와 Phone History 테스트를 같은 통합 기준선에서 실행한다.
- 설치된 release가 검증한 artifact와 동일한지 다시 확인한다.

통과 조건:

- OOM 재시작이 재현되지 않거나 제한·대응이 검증됨
- 전체 필수 테스트가 통과하고, 실패한 선택 검사는 이유가 기록됨
- 운영 release와 검증 artifact의 digest가 일치함

### G6 — 제한 전환과 관찰

**선행:** G5  
**목표:** 전체 사용 전 제한된 실사용으로 위험을 확인한다.

순서:

1. 읽기 전용 검증
2. 합성 업로드·철회
3. 제한된 Phone History 이벤트
4. 제한된 JARVIS 기억 쓰기
5. 새 세션 검색·읽기
6. 삭제·복원·재시작 검증
7. 7~14일 운영 관찰

실사용 20건 미만이면 기간을 연장한다. 합성 자료로 실사용 건수를 채우지 않는다.

## 4. 개발 작업 목록

| ID | 작업 | 담당 | 선행 | 산출물 |
|---|---|---|---|---|
| M-01 | 기준선·release·활성 profile 고정 | 전체 | G0 | baseline report |
| M-02 | 공통 ID·receipt·fence 계약 | JARVIS/SB | M-01 | golden fixture |
| M-03 | Second Brain 철회 기능 release 통합 | SB | M-02 | 검증 wheel·manifest |
| M-04 | 운영 API capability·route 검증 | SB | M-03 | live E2E evidence |
| M-05 | Phone History upload ID 보존 | Phone History | M-04 | sink/export 변경 |
| M-06 | Phone History `retract()` 구현 | Phone History | M-05 | upload→retract 테스트 |
| M-07 | 삭제 후 검색·CAS·재유입 검증 | Phone History/SB | M-06 | tombstone evidence |
| M-08 | JARVIS write→receipt→new-session-read | JARVIS/SB | M-02,M-04 | 실제 provider evidence |
| M-09 | 권한 회수·만료 fence·삭제 claim 검증 | JARVIS/SB | M-08 | fail-closed evidence |
| M-10 | OOM·timer·readiness 안정화 | SB/JARVIS | M-04 | 운영 안정성 보고 |
| M-11 | 전체 테스트·타입·build·artifact 대조 | 전체 | M-07,M-09,M-10 | release acceptance |
| M-12 | 제한 전환·7~14일 관찰 | 오너/전체 | M-11 | 운영 관찰 보고 |

## 5. 오너 승인 또는 실행이 필요한 항목

다음은 개발자가 임의로 실행하지 않는다.

- Second Brain 새 release의 운영 전환과 서비스 재시작
- JARVIS 실제 provider·issuer·read/write 권한 제공
- Phone History가 HTTP API와 직접 Vault 중 어느 방식을 사용할지 결정
- 실제 사용자 기억 저장·검색·철회·복원 테스트 승인
- OOM 분석을 위한 장시간 운영 관찰 승인
- 삭제·복원·rollback의 RPO/RTO 기준 승인
- 제한 전환 후 전체 운영 전환 승인

비밀 토큰 자체는 문서나 evidence에 기록하지 않는다. 환경변수 이름과 설정 경로만 기록한다.

## 6. 중단 조건

다음 중 하나면 해당 단계에서 중단하고 `BLOCKED`로 보고한다.

- 운영 설치본과 검증 artifact의 source/hash 불일치
- 실제 provider 주소 또는 인증 문맥을 확인할 수 없음
- 삭제 후 검색·CAS·receipt 중 하나라도 불일치
- JARVIS가 권한 없는 read/write를 허용함
- Phone History가 네트워크 실패를 성공 또는 삭제로 표시함
- OOM 또는 writer 충돌이 재현되지만 완화책이 없음
- 사용자 변경을 보존할 수 없는 병합 충돌

## 7. 최종 제안

현재는 **G0~G1을 즉시 진행할 수 있고, G2부터는 release 전환 권한과 실제 연동 환경이 필요**하다. 기본 Second Brain 저장·검색은 이미 사용할 수 있지만, JARVIS와 Phone History를 포함한 메인 기억 저장소 완료는 G3~G6의 실제 증거가 확보된 뒤에만 선언한다.

## 8. 2026-09-21 검증 결과 반영

다른 세션에서 수행한 검증 결과를 현재 계획에 반영한다. 결과는 작업 트리 보존본과 최신 기준선의 격리 검증을 포함한다.

### 완료 또는 확보된 근거

- 기존 작업 트리 변경 보존:
  - `/var/tmp/second-brain-pre-sync-20260921/worktree.patch`
  - `/var/tmp/second-brain-pre-sync-20260921/untracked.tar.gz`
- 최신 `origin/master` 기반 별도 worktree에서 `1946 passed, 2 skipped` 보고 확보
- Ruff 통과
- S-04 설정·fixture·cursor 재개 테스트 통과
- 운영 `/ready` HTTP 200, `ready`, 실패 요청 0, 최신 백업 및 격리 복원 확인
- `sb doctor` 8개 항목 PASS
- 설치 클라이언트 버전 확인:
  - Claude Code 2.1.278
  - Codex CLI 0.155.1
  - OMO 5.0.0-beta.79

### 아직 닫히지 않은 항목

- 현재 메인 checkout은 `origin`보다 41커밋 뒤처져 있음
- 전체 basedpyright는 오류가 남아 있음. 전달된 집계는 오류 408건·경고 5,272건이며, 실행 로그를 별도 evidence로 보존해야 한다.
- 현재 확인 시 구형 `second-brain.service`와 `second-brain.timer`는 inactive다. 운영용 `jm-second-brain-refresh.timer`, `jm-second-brain-maintenance.timer`, `second-brain-backup.timer`는 별도 확인 대상이므로 “모든 timer가 inactive”로 기록하지 않는다.
- 실제 Claude·Codex·OMO 로그인 세션의 자동 수집과 문맥 주입은 미검증이다. fixture 수집 테스트를 실사용 세션 인수로 확대하지 않는다.
- S-05~S-09는 `UNGATED_STAGE`로 남아 있다. 외부 카카오톡·메일·JARVIS·전화·위키 계정과 완료 기준이 필요하다.
- 운영 `app/current`의 실제 source commit·release identity가 예상 문서 경로와 일치하는지 추가 대조가 필요하다.

### 단계 상태 갱신

| 단계 | 갱신 상태 |
|---|---|
| G0 | 부분 완료. 보존·진단·readiness는 확인됐지만 checkout 동기화와 release identity 대조가 남음 |
| G1 | 미완료. 공통 ID·receipt·fence 계약의 세 저장소 golden evidence 필요 |
| G2 | 미완료. 철회 구현의 새 release 생성·운영 capability·실제 E2E 필요 |
| G3 | 미완료. Phone History `retract()`와 upload→receipt→삭제 검증 필요 |
| G4 | 미완료. JARVIS 실제 인증 write→receipt→새 세션 read 필요 |
| G5 | 부분 완료. Ruff·readiness·백업은 확인됐고 basedpyright·OOM 안정성·전체 동일 commit 게이트가 남음 |
| G6 | 시작 전. 오너 승인과 실제 제한 관찰 필요 |

이 결과는 G0와 G5의 일부 증거로 사용하며, JARVIS·Phone History 통합 완료 또는 메인 기억 저장소 완료로 표시하지 않는다.
