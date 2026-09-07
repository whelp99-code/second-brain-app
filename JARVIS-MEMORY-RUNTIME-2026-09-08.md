# 자비스 기억 실행기 연결 — 소스 구현·검증

기준일 2026-09-08. 자비스 커밋 `a680fd5`. 운영 서비스 배포·전체 공통 기억 인수 완료는 아니다.

## 연결한 동작

| 진입점 | 이번 구현 | 권한·수명 규칙 |
|---|---|---|
| `memory stage-dispatch <candidate-id>` | 영속 publication/권한에서 예상 결과와 digest-only 제어 명령을 구성 | 같은 입력은 같은 명령을 반환. 별도 기존 ControlPlane 승인이 필요하며 이 명령이 승인하지 않음 |
| `control decide <receipt.json>` | memory.confirm은 공통 review/dispatch root를 등록해 dashboard와 같은 원문을 사용 | 기존 서명·receipt 검사를 그대로 통과해야 함 |
| `control execute <request-id>` | V1/V2 outbox action에 실제 writer·완료 reader를 구성해 실행 | schema3 V2 effect는 기존 lifecycle 경로 유지. claim/fence 없이 쓰지 않음 |
| `memory outbox --once [--limit N]` | 기존 outbox의 queued dispatch와 비동기 완료 확인을 한 번 수행 | 기본 16개 한도. 접수·reconciling·settled를 구분하고 cleanup 오류 반환 |
| `memory outbox list [--limit N]` | 영속 전달 상태를 제한된 개수로 조회 | 기억 원문이나 새로운 승인/쓰기 요청을 생성하지 않음 |
| dashboard 기본 executor | 공통 production outbox를 주입 | 주입된 읽기 전용 adapter만 있는 경우 암묵적 provider writer를 만들지 않음 |
| dashboard 기존 1초 주기 검사 | 한 번에 1개 작업을 처리, 진행 중 cycle과 겹치지 않음 | 새 timer/queue를 만들지 않음. 상태 변경은 memory topic으로 명시 통지 |
| dashboard 종료 | HTTP 처리와 outbox tick을 모두 drain한 뒤 소유 transport·DB 종료 | 빌려 받은 transport는 닫지 않음. `startDashboardCli().close()`는 Promise이므로 await 필요 |

기본 spool은 authority DB 디렉터리의 `memory-review-spool`, `memory-dispatch-spool`이다. 명시적 옵션, `JARVIS_MEMORY_REVIEW_SPOOL_ROOT`/`JARVIS_MEMORY_DISPATCH_SPOOL_ROOT`, 기본 경로 순으로 선택한다. 임의 새 원문 위치를 만들거나 기존 자료를 옮기지 않았다.

완료 reader에는 schema4 `record-set-v1`, 전체/페이지 각각 262144바이트, excerpt 4096바이트 상한을 명시한다. 일반 dashboard 검색 예산은 유지한다. 설정된 `read_fence`는 같은 transport의 완료 reader까지 전달한다. 서명 없는 fence를 임의 생성하거나 tombstone 검사를 느슨하게 하지 않는다.

## 검증

- 회귀 **100 passed / 39 files (51.82초)**: outbox, 기존 승인 executor, task32 경로, dashboard CLI와 remote approval. `/var/tmp/jarvis-outbox-production-final-tests.log`.
- 추가 **11 passed / 4 files (8.72초)**: 기존 interval의 실제 queued 처리·중복 전송 방지, 명시 topic 통지, SSE, tick 중복/종료/오류 복구. 위 회귀와 일부 중복하므로 두 수치를 합산하지 않는다. `/var/tmp/jarvis-outbox-production-tick-tests.log`.
- deferred transport로 HTTP 실행을 정지시킨 뒤 close→응답 해제 순서를 주입했다. close는 실행이 끝날 때까지 기다리며 DB에 reconciling 결과를 기록한 뒤 종료한다.
- nonzero tombstone fence 설정은 생산 구성 함수에서 전달되어 읽기가 통과하고, 같은 결과를 unfenced로 읽으면 거부된다. 이 검사는 합성 fence와 transport를 사용하므로 운영 서명키 설정의 증거는 아니다.
- 변경 ESLint·backend build·독립 읽기 전용 검토 통과. 마지막 build `/var/tmp/jarvis-outbox-production-final-build.log`. Python 소스 변경이 없으므로 전체 Python 검사를 이번에 재실행하지 않았다.
- 초기 집중 검사에서 `.chatgpt2codex`의 과거 복제본 health 검사가 현재 migration과 불일치해 실패했다. 최종 검사에서는 `.runtime-tmp`, `.omo`, `.chatgpt2codex`를 명시 제외했다. 현재 dashboard CLI 검사는 통과했으며 오래된 복제본을 수정하지 않았다.

## 실제 MCP와 CLI 실행 경로

Second Brain 루트에서 자비스 backend 빌드 후:

```bash
TMPDIR=/var/tmp node scripts/jarvis-memory-acceptance.mjs ../Orca-JARVIS --owner-confirmed --approval-rollback --runtime-cli --record-limit --record-budget --sensitive
```

하네스가 이제 `execute()`의 실제 CLI 경로로 stage-dispatch, control execute, 다음 memory outbox --once를 호출한다. CLI 호출마다 새 authority 연결과 소유 provider transport를 구성·종료한다. 테스트 clock과 격리 provider launcher/config만 주입한다. 새 프로세스의 shell CLI를 직접 실행한 검사는 아니며, 실제 별도 MCP 프로세스는 사용한다.

관측 결과: rollback→새 합성 owner 승인→CLI dispatch→provider pending/proved→다음 CLI cycle settled. 민감 기억 64개를 원래 reader와 독립 MCP 클라이언트에서 회수했다. provider 재전송 replayed=true, 재apply idle, 추가 dispatch 0, terminal 재확인 settled, review 원문 0개, cleanup 오류 없음. `/var/tmp/sb-jarvis-runtime-cli-acceptance.log`.

**원래 control command는 `uncertain`으로 남는다.** 이 값도 하네스 출력에 기록했다. outbox settled를 명령 전체 완료로 보고하지 않는다.

## 필수 잔여와 다음 순서

1. I1-e 후속: outbox 완료 영수증·원래 제어 명령·fence를 결합해 `uncertain → terminal` 상태를 반영한다. 새 provider dispatch나 새 승인으로 해결하지 않는다. 취소·만료·replay·중복 완료 시나리오 필요.
2. 운영 read fence: 기본 CLI/dashboard 구성에는 서명키·provider identity·삭제 high-water를 자동 조합하는 설정이 아직 없다. 주입 가능한 factory 전달만 구현됐다. tombstone이 있는 운영 저장소는 서명된 최신 fence 설정과 실제 삭제→추가 저장→조회 검증이 필요하다.
3. I1-a/c 후속: 실제 후보 수집→review/dispatch publication 생성과 dashboard에서 저장 명령을 준비하는 전체 사용자 흐름을 검증한다. 현재 CLI helper 존재만으로 모든 auto-staged 후보나 실제 에이전트 앱의 흐름이 연결됐다고 하지 않는다.
4. I1-d 일반 LF 입력, V2 정정·재조회, 프로젝트/사용자/에이전트 범위, 실제 다른 앱의 공유를 이어간다.
5. B3 읽기 잠금 지연/과거 잔여물, B5 문맥 선택·전달 기록·검증된 결과, B6 운영 전환/복구, B7 품질/부하, B8 조건부 hybrid는 기존 원장 범위를 유지한다.

운영 서비스 재시작·release 교체·활성 generation 변경·push는 수행하지 않았다. 합성 승인과 격리 자료의 실프로세스 검증을 현실 업무 성공이나 운영 배포로 확대 해석하지 않는다.
