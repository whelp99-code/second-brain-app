# 차단된 기억 후보의 재분류·승인·remember 전송 수정

JARVIS `0c0508a`, SB 인수 도구 `7e01e2b`. 실제 task 결과의 자동 수집을 완성하기 위한 선행
차단 집행을 수정했다. 기존 verified_outcome 분류는 서명된 성공 증거가 없으면 거부하며 실제
task collector는 아직 보류 상태다. 이번 조사에서 이미 존재하는 후보 쓰기 경계의 누락을 확인했다.

## 재현과 구현

| 발견 | 수정 | 검증 |
|---|---|---|
| 후보 검토 화면은 숨기지만 classify 재생은 기존 결과 반환 | writer transaction 안에서 후보 ID 차단 검사 | 같은 요청·다른 idempotency 입력 거부, idempotency 증가 없음 |
| 차단 전에 준비한 owner 승인이 후보와 dispatch 원문을 발행 | decision staging 재검사 및 승인 적용 transaction 안 검사 | 준비 후 격리 시 승인 실패, decision/dispatch publication 0 |
| 승인 후 차단해도 remember 저장 명령 준비 가능 | 기존 V1 write authority에 projection 차단 적용 | 실제 HTTP stage-dispatch 거부, 신규 dispatch command 0 |
| queued/claimed 후보를 차단해도 전송 attempt 생성 가능 | enqueue writer lock 안, claim, markDispatch transaction 검사 | 큐/claim 이후 차단 시 attempt 0 |
| 직접 V1 adapter 호출이 차단을 무시 | 최종 write authority에서 동일한 차단 확인 | 정상 wire 입력으로 transport 진입 후 같은 입력 차단 시 추가 호출 0 |
| legacy 정정 후보의 검사와 승인·settlement가 분리됨 | 전체를 immediate transaction으로 결합 | 별도 SQLite writer가 검사 구간에서 SQLITE_BUSY, 완료 후 격리 가능 |

기존 isProjectionIdSuppressed(candidate_id)의 읽기 의미를 쓰기에도 적용한다. 허용된
dashboard_projection kind의 후보 ID를 사용했고 새 projection kind나 SQL migration을 추가하지 않았다.
compaction inventory의 candidate/outbox 분류는 이 API의 projection kind와 별개다.
reject는 새 기억 저장을 허용하지 않으므로 유지한다. 조회 원문을 물리적으로 지웠다는 의미는 아니다.

## 검증의 범위

- 최초 잘못된 fixture kind로 난 4개 오류는 결함 재현이 아니다. 수정한 fixture에서 실제 guard 누락 4개를 재현했다.
- 관련 7파일 39 passed. 정정 transaction/실제 target tombstone 보강 후 2파일 7 passed.
- 직접 adapter 검사에서 기존 outbox fixture의 placeholder request digest가 parser에서 먼저 거부됨을
  실제 인수가 드러냈다. digest를 재계산하고 parser 통과·정상 transport 진입을 먼저 확인하도록
  회귀와 도구를 바로잡았다. 최종 집중 1파일 6 passed. 위 수치는 중복이 있어 합산하지 않는다.
- backend TypeScript·변경 ESLint·격리 정규 build·diff·도구 syntax 통과. 전체 backend/frontend/SB 회귀는 아니다.
- 별도 모델 검토에서 정정 transaction 결함과 V2 별도 경로를 발견했다. 전자는 수정했고 후자는 아래
  다음 필수 범위로 명시한다. “모든 기억 쓰기 차단 완료”로 판정하지 않는다.

[기계 증거](CANDIDATE-SUPPRESSION-WRITES-2026-09-08.json). 최종 actual fixture는
`/var/tmp/jarvis-candidate-suppression-Q2quSD`, build는
`/var/tmp/jarvis-candidate-suppression-build-wx8yq3iz`다. 독립 Node 프로세스 3개 모두 exit 0.

| 실제 실행 | 결과 |
|---|---|
| 정상 입력과 격리 후 같은 provider 요청 | 결정적 transport fixture 1회 → 추가 0회 |
| DB를 닫고 새 프로세스로 재개 | classify 재생 거부, provider 호출 0, queued outbox failed, attempt 0 |
| 실제 HTTP와 준비된 owner receipt | 검토 200·stage 202 → 격리 후 검토 404·본문 없음·승인 거부 |
| 승인 실패의 원장/파일 발행 | owner decision 0, dispatch publication 0 |

검증 서버·DB는 종료했다. 합성 DB·review/dispatch fixture는 남아 있다. 실제 SB provider/모델/운영
데이터를 사용하지 않았으며 현재 테스트의 accepted는 fixture transport 응답이다. native 기억 공유와
운영 저장 순환 전체를 이번 결과로 증명하지 않는다.

재현: 자비스 소스 사본에서 정규 backend build 후 SB 작업공간에서
`TMPDIR=/var/tmp node scripts/jarvis-candidate-suppression-acceptance.mjs /absolute/isolated/source-root`.

## 다음 필수 수정과 보류

**P0 V2 정정 전송:** MemoryCorrectionSaga.prepare → destructive preparation/materialization →
MemoryCorrectionStore.beginDispatch → adapter dedicatedAuthority(correct)는 V1 write authority를
거치지 않는다. legacy 정정의 owner confirmation은 이번에 보호했지만 승인 이후의 이 별도 경로는
미완료다. preparation INSERT와 tombstone 생성 transaction, 최종 dispatch·adapter의 candidate 검사를
결합해야 한다. 정정 작업 자체가 추가하는 이전 target tombstone과 후보 원본의 독립 차단을
구분하며, 이미 전송된/uncertain 요청의 관측·폐기는 계속해야 한다.

**P0 원본→파생 계보:** task_id/request/run/completion과 후보·검토 원문·dispatch·provider record의
영속 출처 관계가 필요하다. 이번의 이미 연결된 후보 ID 검사로 자동 계보가 생기지는 않는다.
수집 전, 승인 전, 전송 전/중, 저장 후 원본 차단과 재색인·오래된 복원에서 두 client 회수를 검증해야 한다.
이 조건 전까지 task 자동 collector와 무조건적인 native 문맥 주입은 계속 보류한다.

**기존 전체 범위 유지:** native rollout/SQLite/WAL/백업 소유권·폐기, DB→외부 수신 fence,
검증된 사용자/프로젝트 ACL, 실패 결과 capture, 실제 session/compaction·예산,
검색 근거 충분성·지연·실제 질문, 앱별 채택, 전역 연결 배지 및 운영/복구 인수는 미완료다.
서비스 배포·재시작·운영 DB 변경·push는 하지 않았다.
