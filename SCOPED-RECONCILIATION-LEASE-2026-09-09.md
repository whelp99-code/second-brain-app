# Scoped 재조정 lease와 만료된 원래 요청 복원

## 구현

JARVIS 구현 커밋: `c5f3849`.

최종 완료를 기록할 worker가 원래 전송 시도를 복원하고 로컬 재조정 권한을 얻는 경로를 추가했다. 기존 outbox/attempt와 lease 열을 재사용하며 새 큐나 서버 worker를 만들지 않았다. DB schema 및 SB 제품 소스 변경은 없다.

JARVIS `memory-scoped-reconciliation.ts`는 다음을 제공한다.

- `readMemoryScopedReconciliationRequest`: reconciling인 scoped-v4 행만 읽는다. private spool을 원래 dispatched_at 시점에 decode하고, 등록 binding·원본/후보/분류·scope 검토 ID·원래 attempt/fence/invocation·예상 artifact·outbox ID와 대조한다. 현재 시간이 쓰기 만료 뒤여도 복원할 수 있다. 이는 새 쓰기나 provider 읽기 권한이 아니다.
- `claimMemoryScopedReconciliation`: 현재 lease가 없거나 만료된 특정 요청을 원자적으로 claim한다. 재조정 lease_fence만 증가하고 원래 dispatch_fence는 보존한다. 현재 worker ID, 시간과 1~900000ms 범위를 검사한다.
- `requireMemoryScopedReconciliationLease`: outbox/profile/state/worker/lease fence/dispatch fence/정확한 expiry와 현재 시간을 검사한다. 후속 쓰기는 이 검사를 동일 트랜잭션 안에서 유지해야 한다.
- `releaseMemoryScopedReconciliation`: 유효한 현재 lease만 해제한다. stale worker, 만료된 lease, 과거 시계로 새 lease를 해제할 수 없다.

원래 데이터 복원은 내용의 보존·identity 검사이고, 현재 MCP 접근은 기존 인증된 읽기 경로에서 따로 수행한다. 쓰기 요청 만료를 재조정 lease의 만료로 재사용하지 않으며, lease를 얻었다고 재전송할 수 없다.

## 검증

최종 관련 검사 33개/4파일 통과(27.52초), 격리 TypeScript emit 및 변경 파일 ESLint 통과. 최종 emit 후 두 실제 프로세스 인수를 다시 실행해 통과했다. 최초 재실행은 SB 디렉터리에서 JARVIS fixture 상대 설정 경로를 찾지 못했으며, 요구되는 JARVIS 작업 디렉터리에서 재실행했다.

신규 검사에서는 만료된 요청의 정확한 복원, 다른 worker 배제, fence 회수, 과거 worker/시간 거절, 해제 후 재사용 거절, provider/attempt/본문/시간 손상 및 잘못된 lease 입력을 확인했다. 기존 DB의 expected artifact 불변 trigger가 변조를 먼저 거절했으며, 별도로 spool 파일 변조도 거절했다.

실제 독립 프로세스 경합은 7개 child process를 사용했다. 동시 claim 2개 중 승자 1개, 원래 dispatch fence=1 보존, reconcile fence=2→3, stale release 거절, 해제한 lease 검사 거절, dispatch attempt=1, FK 오류=0을 확인했다. 시계는 명시적 fixture이며 sleep을 사용하지 않았다.

기존 실제 stdio MCP 인수에도 lease를 연결했다. 만료된 요청은 새 복원 함수의 결과로 공급한다. MCP 상태/현재 artifact 관찰·수락 회수 후 별도 기록 프로세스를 commit 직후 exit73으로 종료하고 다시 실행해도 재조정 lease가 보존됐다. 이후 유효한 worker가 해제했다. 수락 event1/attempt1을 유지했고 자비스는 reconciling이다.

[실제 프로세스 결과](SCOPED-RECONCILIATION-LEASE-2026-09-09.json). provider 내부 쓰기와 인증 세션/키/시계는 fixture다. 운영 쓰기 인증·배포·최종 완료 인수로 해석하지 않는다.

## 최종 완료의 남은 연결

이번 구현으로 만료된 쓰기 요청을 새로운 전송으로 처리하지 않고 복원할 수 있고, 동시에 동작하는 reconciliation writer를 fence로 구분할 수 있다. 다음은 현재 완료 관찰을 원래 attempt와 묶은 immutable 원장 증거, scoped settlement 검증, control 완료의 원자적 기록 및 commit 전후 복구다.

기존 legacy settlement receipt를 scoped용으로 위장하는 방식은 계속 보류한다. 현재 read observation이나 lease 자체를 task 성공 증거로 쓰지 않는다. 원래 control command/승인·현재 철회·suppression 검사는 최종 완료 경로에 결합해야 한다. 최초 활성 세대 이전 조회·공개 scoped 쓰기·실제 agent 운영·전체 M1–M14 인수도 남는다.

운영 DB/설정/서비스·vault를 변경하지 않았고 push·배포하지 않았다. SB 제품은 변경하지 않아 전체 SB 검사는 반복하지 않았으며, 이전 전체 1,260통과/2skip는 [이전 기록](SCOPED-ACK-RECOVERY-2026-09-09.md)의 결과다.
