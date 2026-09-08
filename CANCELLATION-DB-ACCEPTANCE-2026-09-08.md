# 실제 DB 근거의 취소 의향 발급·중단 복구 인수

기준일 2026-09-08. JARVIS 제품 `88fcd89`, Second Brain 제품 `df9412c`.
자비스 인계의 기존 Second Brain 유지·공통 기억 우선 원칙에 따라, 이미 구현한 취소 계약을 JARVIS AuthorityDb에 연결했다. 이번 단위의 Second Brain 제품 코드는 변경하지 않았다.

## 수정한 문제와 구현

기존 순수 서명 함수만으로는 원래 요청이 실제 미전송인지 증명할 수 없었다. 이제 정정 materialization과 동일 transaction에서 원래 요청의 delegation/target/scope/tombstone 및 envelope/idempotency 메타데이터를 보존한다. 대체 본문을 취소 테이블에 복제하지 않는다.

발급 transaction은 queued 상태, fence 0, attempt 부재, 해당 lane 비활성, cursor 미통과와 실제 candidate suppression link/event를 검증한다. 준비 기록·원래 요청·삭제 이력도 대조한다. 단순 quarantine은 취소 근거로 인정하지 않는다. 현재 활성 키로 서명하고 과거 공개키는 원래 delegation 검증에만 사용한다.

새 migration 072는 source와 intent 불변 저장 및 원래 요청의 후속 claim/dispatch/attempt 차단을 제공한다. 기존 001~071은 변경하지 않았다. 과거 철회한 자동 retirement 시제품을 복구한 변경이 아니며 cursor를 넘기지 않는다. SQL 방어와 공개 API의 `MEMORY_REQUEST_CANCELLED` 오류를 함께 적용했다.

## 실제 프로세스 검증

[기계 판독 증거](CANCELLATION-DB-ACCEPTANCE-2026-09-08.json). 재현 스크립트는 자비스의 `scripts/cancellation-db-acceptance.mjs`이며 운영 dist 대신 별도 TypeScript 출력 디렉터리를 사용했다.

| 사례 | 관측 |
|---|---|
| 취소 먼저 저장 → 즉시 강제 종료 | exit 77 이후 새 Node 프로세스에서 동일 canonical intent 재생 |
| 저장된 취소 뒤 원래 요청 선점 | `MEMORY_REQUEST_CANCELLED` 거부 |
| 원래 요청 선점 뒤 취소 발급 | `MEMORY_CANCELLATION_UNSENT_UNPROVED`, 저장 intent 0개 |
| 본문·외부 영향 | 원문 spool 보존, 원래 transport 호출 0회 |
| 실제 DB 발급 결과를 Python으로 검증 | 5,752 canonical bytes 일치, 정상 수락 |
| 알 수 없는 현재/과거 키·변조 서명 | Python에서 모두 거부 |

이 검증은 실제 SQLite와 분리된 프로세스를 사용하되 대상과 키·시각은 격리 fixture다. 외부 provider 전송의 동시 경합이나 실제 대상 접수·삭제까지 검증한 것은 아니다.

## 테스트와 정적 검사

- 발급·기존 취소·정정·migration: 5파일 43통과, 19.39초. 최종 typed API 오류 보강 전 관측이다.
- effect/control/upgrade 범위: 9파일 32통과, 51.40초. 위 최종 보강 전 관측이다.
- 최종 변경 후 DB 취소·정정 억제·dispatch·32 worker 동시성: 4파일 20통과, 16.65초.
- TypeScript noEmit, 변경 파일 ESLint, 격리 emit, diff 공백 검사 통과. 중복 테스트를 합산하지 않는다.
- Second Brain 전체 테스트는 이번 단위에서 재실행하지 않았다. Python 교차 검증은 실제 DB 발급 의향의 계약 검사다.

## 다음 구현과 유지하는 보류

1. 현재 권한·키 철회를 전송 시 다시 확인하고, 실제 DB 의향을 provider 취소 접수에 연결한다. 외부 전송과 취소의 경합을 인수한다.
2. 정확한 provider 결과와 실제 JARVIS 로컬 억제 증거가 모두 있을 때만 cursor를 완료한다. 취소 seq1 → 정상 V2 seq2를 실제 전 구간에서 검증한다.
3. 만료/철회된 저장 intent는 자동 재발급하지 않는다. provider 상태와 조정할 정책이 필요하다. 과거 요청에 source가 없으면 정확한 원 요청으로 등록하며 추정하지 않는다.
4. 사용자/프로젝트 범위, 원작업 계보, native 세션·WAL·백업 수명, 실제 앱 순환, 검색 평가·화면·운영 복구 목표를 유지한다.

운영 DB migration, 서비스 재시작, 배포, push는 하지 않았다. 전체 중앙 기억의 운영 인수는 미완료다.
