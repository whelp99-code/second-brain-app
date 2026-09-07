# 자비스 기억 순환: 실제 프로세스 인수 검사

상태: 단일 줄 및 Unicode 줄 구분자로 구성한 64개 record의 격리 remember 순환 통과. 최신 검증은 [2026-09-08 결과 대응 계약](REMEMBER-ARTIFACT-CONTRACT-2026-09-08.md)을 따른다. 아래 초기 관측은 이력이며 운영 진입점·실제 업무 결과·일반 LF 입력까지 완료됐다는 뜻은 아니다.

## 실행 경로

`scripts/jarvis-memory-acceptance.mjs`는 빌드된 자비스 라이브러리와 기존 서명 fixture를 사용한다. 새 임시 authority DB, 개인 spool, provider generation/request journal을 만든다. 운영 DB·키·서비스를 사용하지 않는다. 고정 시계는 2026-08-31 03:30 UTC다.

1. 검증된 결과 형식의 합성 fixture를 실제 candidate 분류·spool 경로로 준비한다. 현실 업무의 검증 성공을 새로 주장하지 않는다.
2. 자비스 ControlPlane이 서명된 dispatch 명령을 stage/approve/claim한다.
3. MemoryOutboxService와 실제 write adapter가 별도 Python MCP 프로세스로 요청한다. MCP 도구 스키마·요청 검증·원자 접수·원장 저장은 실구현이다.
4. provider RequestExecutor를 별도 프로세스로 실행하여 새 generation을 생성·활성화하고 proved 상태를 기록한다.
5. 실제 read adapter가 결과를 확인하고 자비스 outbox가 settled 영수증을 남긴다.
6. 같은 adapter가 새 기억을 재조회한다. 별도 transport/MCP 프로세스를 사용하는 두 번째 클라이언트도 같은 record ID를 회수한다.
7. 동일 요청의 네트워크 재전송을 모의한다. provider replayed=true, 추가 executor 실행 idle, outbox 추가 dispatch=0을 검사한다.

현재 검사에서는 **하네스가 expected_artifact를 생성하고 executor와 reconciliation을 명시적으로 호출한다.** 운영에서 자동으로 연결돼 있다는 증거로 사용할 수 없다. 두 번째 클라이언트도 독립 MCP 프로세스이며 Codex/Claude 앱 자체의 자동 수집·주입 검증과는 다르다.

## 재현한 결함과 수정

첫 실행은 pending→proved→settled까지 갔지만, 기존 reader 재사용에서 `SECOND_BRAIN_PROVIDER_VALUE_INVALID`로 실패했다. adapter의 unboundGenerations가 세션 전체에 고정돼 정상적인 새 generation을 거부했다.

자비스 `471cab3`은 public read마다 독립된 operation 상태를 만든다. 같은 검색의 후속 페이지는 여전히 같은 generation인지 검사한다. 다음 조회와 동시 조회는 이전 요청의 mutable pin을 공유하지 않는다. 삭제 fence의 기존 검사도 유지한다.

추가로 schema4 recentChanges에는 records 배열이 없다는 이유로 generation metadata가 제거되어 후속 페이지와 일치 검사가 실패했다. 협상된 schema4 프로필에서는 이 메타데이터를 보존하도록 수정했다. 다음 세대 조회·한 요청 안의 혼합 세대 거부·최근 변경 회귀 테스트가 있다.

## 최종 관측

| 단계 | 결과 |
|---|---|
| provider 접수 | pending |
| provider apply | proved / PROVIDER_PROVED / fence 1 |
| provider 상태 조회 | proved |
| 자비스 reconciliation | settled 1, conflict 0, failed 0 |
| 자비스 outbox | settled |
| 동일 reader 재사용 | current / evidence 1 |
| recentChanges | current |
| 두 번째 MCP 클라이언트 | current / 같은 record ID |
| 동일 요청 재전송 | replayed=true |
| provider 재실행 | idle |
| outbox 재실행 | dispatched=0 |

로그: `/var/tmp/sb-jarvis-acceptance-final.log`. 자비스 기억 관련 단위 247개 통과(26개 파일), 변경 파일 ESLint·backend build 통과, 독립 읽기 전용 코드 검토 완료. Python fixture는 Ruff 및 타입 오류·경고 0. 기존 Python 전체 기준선 548 passed/2 skipped를 새 전체 실행 결과로 바꿔 보고하지 않는다.

## 재현 명령

자비스 backend 빌드를 먼저 마친 뒤 Second Brain 루트에서 실행한다. Node 24 및 이 저장소의 동기화된 Python venv가 필요하다.

```bash
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs ../Orca-JARVIS
```

`SB_TEST_PYTHON`으로 Python 실행 경로를 지정할 수 있다. 하네스는 임시 자료에만 쓰며 종료 시 transport와 DB를 닫고 sealed 디렉터리의 읽기 전용 모드를 해제한 뒤 해당 fixture를 정리한다. 표준 단위 테스트에 상대 리포 의존성을 강제로 추가하지 않는 명시적 인수 검사다.

## 남은 I1 필수 하위 작업

| ID / 우선순위 | 확인된 문제 | 수정·완료 기준 |
|---|---|---|
| I1-a / P0 | 운영 src에서 MemoryOutboxService 생성이 없고 dashboard/CLI executor는 outbox에 undefined를 전달 | 기존 transport·권한·fence를 사용하는 outbox를 실제 진입점에 구성하고 승인된 요청의 실행을 확인 |
| I1-b / P0 | 원문 수명·owner-confirmed remember의 권한 연결은 소스 수정 및 실제 프로세스 순환 통과 | 자비스 64b255b/d553327. 바깥 DB rollback 후 metadata 재승인 복구, 운영 정리/layout 연결은 남음 |
| I1-c / P1 | c7c5182에서 영속 publication/권한 기반 selector 구성기 구현·격리 실제 순환 통과 | runtime/UI 명령 staging 호출에 연결. 사용자에게 내부 hash 계산을 요구하지 않음 |
| I1-d / P1 | c7c5182의 전체 record 대응과 provider 민감도·입력 한도 보강으로 64개 격리 순환 통과 | 일반 LF 본문 계약은 여전히 미완료. 완료 reader의 record-set-v1 예산을 운영에 명시 주입 |
| I1-e / P1 | provider 비동기 완료 이후 outbox reconciliation의 운영 호출이 없음 | 기존 주기적 진입점에 연결. 접수만으로 완료 표시하지 않고 재시작·중복·uncertain을 검증 |

이 다섯 항목은 보류할 선택 기능이 아니라 B4 완료 조건이다. 별도 큐 서버나 두 번째 기억 DB를 만들지 않고 기존 자비스 상태기계와 세컨드브레인 단일 writer를 연결한다. source-level 승인 정책을 우회하거나 예전 요청의 서명·digest를 치환하지 않는다.

## 2026-09-08 후속 — 승인 원문 보존과 종료 후 정리

자비스 `64b255b`에서 승인/거절 처리 중 원문 unlink를 제거했다. 바깥 ControlPlane DB transaction이 뒤에서 실패하더라도 원문은 남는다. 별도 cleanup은 확정된 candidate/outbox 종료 상태만 대상으로 하며, caller transaction 안에서는 실행을 거부한다. queued/claimed/dispatching/reconciling은 확인 기한이 지나도 원문을 보존한다. 원문 envelope와 원장 digest를 확인하고, 없는 파일만 멱등 성공으로 취급한다.

완료 후 원문이 없어도 같은 claimed command는 저장된 terminal 결과를 재확인한다. target/args/digest/receipt/fence가 바뀐 명령은 거부한다. cleanup 오류는 저장 완료를 명령 실패로 바꾸지 않으며 cycle의 `cleanup_error=MEMORY_REVIEW_CLEANUP_FAILED`로 반환하고 다음 cycle에서 재시도한다. **이 오류의 운영 표시와 주기적 cleanup 호출은 I1-a/e에 남아 있다.**

실제 CandidateStore→dashboard mutation staging→서명된 ControlPlane 결정→dispatch 복원 검사에서 또 다른 결함을 재현했다. review의 후보 입력용 idempotency key는 provider 요청용 key와 해시 domain·입력이 달랐다. 새 dispatch는 기존 provider 계약대로 immutable candidate/classification/operation에서 key를 만든다. 이미 발급한 dispatch/서명 자료를 자동 재작성하지 않는다.

검증:

- 자비스 집중 회귀 **91 passed / 37 files / 39.27초**. 승인/거절 transaction rollback, 거절 후 정리, 변조된 원문 보존, timeout 이후 진행 중 원문 유지, terminal 재확인·변조 거부, 삭제 실패 후 재시도를 포함한다.
- 변경 파일 ESLint와 backend build 통과. 독립 검토의 terminal cleanup 오류 지적을 반영하고 재검토했다.
- 실제 격리 MCP/outbox 순환 재실행: pending→proved→settled, 같은 reader/두 번째 MCP client current, provider replayed=true, 추가 apply idle/dispatch 0. **review 파일 0개, terminal 재확인 settled, cleanup_error 없음**을 추가 확인했다.
- 로그: `/var/tmp/jarvis-review-handoff-final-tests.log`, `/var/tmp/jarvis-review-handoff-build.log`, `/var/tmp/sb-jarvis-review-handoff-acceptance.log`. Python 구현을 바꾸지 않았으므로 기존 전체 Python 548 passed/2 skipped를 이번 재실행 수치로 보고하지 않는다.

### 64b255b 시점에 확인한 후속 결함

`hasSecondBrainWriteAuthority`는 `memory_candidate_authority_claims`를 inner join하고 원래 분류의 authority/receipt 시간을 검사한다. 반면 `labeled_inference` 분류는 이 claim을 만들지 않고, 이후 owner confirmation은 candidate와 owner decision ledger에만 기록한다. 따라서 원문 복원 성공만으로 승인된 inference의 실제 provider 쓰기가 가능해진 것은 아니다. 기존 서명 결정·취소·만료·내용 결합을 검증하는 소비자 권한 연결이 필요하다. 추론을 검증된 업무 사실로 승격시키는 우회는 하지 않는다.

또한 승인 처리에서 dispatch 파일 발행은 DB transaction 안에서 이루어진다. 그 뒤 바깥 event insert/commit이 실패하면 원문은 이제 보존되지만 dispatch metadata 파일은 남을 수 있다. 다른 승인 receipt로 재시도할 때 이 파일과 충돌하는지, committed publication과 미커밋 잔여물을 어떻게 구별할지는 후속 복구 검사 대상이다. 이번 rollback 테스트는 원문 보존까지 검증했으며 모든 재승인 복구를 검증했다는 뜻은 아니다.

원문 삭제 정책의 실제 compaction/layout 연동, rejected/expired 상태로의 운영 전환, 승인 전체 권한 경로는 B4/B6 완료 조건으로 계속 유지한다. 운영 서비스·release·active pointer는 전환하지 않았다.

## 2026-09-08 후속 — owner-confirmed remember의 실제 저장 순환

자비스 `d553327`은 required_confirmation 기억 추가를 기존 owner decision/attempt/family, ControlPlane 요청과 서명 영수증, personal redemption에 연결한다. 기존 분류·원문·주제·보관 정책과 실제 승인 대상이 일치해야 하며, 승인 서명·취소·만료를 확인한다. 원래 분류의 시간 대신 실제 owner receipt 발급 시간을 사용한다. 새 dispatch 만료는 후보/confirmation/실제 승인 영수증 중 가장 이른 기한으로 제한한다.

기존 auto-staged 경로에도 요청 원문·주제·보관 기간·민감도·목적·생성 시각을 실제 후보와 비교하는 검사를 추가했다. 이전 adapter 단위 fixture는 승인된 입력과 다른 원문/주제를 보내도 통과하고 있었으므로, 올바르게 일치하는 fixture로 수정하고 다른 내용의 재해시 요청을 거부하는 검사를 추가했다. inference의 input_class는 그대로 유지하며 검증된 업무 사실로 바꾸지 않는다.

검증은 **91 passed / 36 files / 41.40초**, transport fixture의 필수 reason 타입 보정 뒤 승인 경로 **7 passed** 재검사, 변경 파일 ESLint와 backend build 통과다. 독립 검토에서 발견된 V1 정정 대상 결합 문제는 아래와 같이 보류했다. 로그는 `/var/tmp/jarvis-owner-confirmation-final-tests.log`, `/var/tmp/jarvis-owner-confirmation-posttype-tests.log`, `/var/tmp/jarvis-owner-confirmation-build.log`다.

새 `scripts/jarvis-owner-memory-fixture.mjs`는 합성 inference 입력을 실제 CandidateStore로 분류하고, dashboard mutation staging과 서명된 ControlPlane 결정을 거쳐 요청을 만든다. 이를 다음 명령으로 별도 provider MCP에 전달한다.

```bash
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs ../Orca-JARVIS --owner-confirmed
```

실제 관측: **pending→proved→settled, reader 재사용 current 1개, 독립 MCP 클라이언트 current/동일 record ID, replayed=true, 재apply idle, 추가 dispatch 0, review 파일 0, terminal 재확인 settled, cleanup 오류 없음**. 로그는 `/var/tmp/sb-jarvis-owner-confirmed-acceptance.log`. 기존 verified fixture 경로도 같은 결과로 통과했다(`/var/tmp/sb-jarvis-owner-auto-regression.log`).

이 검사는 실제 운영자 승인이나 현실 업무 수행이 아닌 격리 DB의 합성 승인이다. 하네스가 expected selector를 만들고 apply/reconcile을 호출한다는 범위는 그대로다. 실제 앱 연결과 runtime 자동 생성/주기적 관측 완료를 뜻하지 않는다.

### 보류: owner-confirmed V1 correct 확장

기존 V1 memory.confirm 서명 args에는 correction target/prior가 없고, attempt의 expected_prior_json은 변경 방지된 정본이 아니다. 이 열만 비교하면 승인 이후 다른 prior에 같은 owner 서명을 적용할 수 있다는 독립 검토 결과가 있었다. 따라서 신규 owner-confirmed 권한 경로는 **remember만 허용**한다. correct는 기존 V2 target/delegation 계약에 연결하는 방식으로 완성해야 한다. 단순 비교로 V1을 열거나 기존 서명을 새 대상으로 재해시하지 않는다.

재개 기준: immutable target version/membership와 정정 prior가 승인·provider 요청에 결합되고, 승인 후 대상 변경을 주입한 거부 검사 및 실제 정정·재조회가 통과할 것. 바깥 rollback의 dispatch metadata 잔여물 재승인 복구와 I1-a/c/d/e는 계속 남아 있다.
