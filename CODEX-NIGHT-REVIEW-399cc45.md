# 야간 독립 검토 — 399cc45 미통과

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`, 사용자 야간 독립 검증 위임. 원래 Codex 직접 실행 아님. `2026-09-11T17:08:15.143629+00:00`. **제품 준비/운영 최종 인수 아님.**

## 고정 후보와 바이트

제출 `399cc45dd92f26c9cdeac484f14f144739d00aa2`, SB source `f94d0733f84b23db03a053b4be513a257211c938`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. SB archive/휠/설치물 Python182개 일치.

JARVIS source `0b8ace5`, 제출 dist `/var/tmp/jarvis-artifact-0b8ace5/source/dist`, inventory `501d5ba5f7677c980bd121f9a5573b5451e68a82926667b8904c22cd46a0bd24`/34779. 설치 게이트가 이 inventory를 확인했지만 **그 dist가 해당 source의 빌드라는 것은 입증하지 못했고 실제로 불일치한다.** 제품 tracked 파일1137개(`src`,`tests`,package/tsconfig/lockfile)는 Git 소스와 일치한다. 전체 tracked1598개 조사에서 과거 `.omo` 증거12개 부재/AGENTS 변경은 별도로 기록했으며 제품 바이트 불일치 원인으로 세지 않았다.

원본 로그/harness: `/var/tmp/codex-night-399cc45-wh2i5plf`. 검토 종료 HEAD는 고정 제출과 동일. 제품 소스/테스트 수정, 운영 전환/인증 복사/사용자 기록 삭제/push 없음. 아래 진단 재빌드는 이 별도 리뷰 디렉터리에만 썼다.

## N1-build-identity (P1): 제출 dist에 이번 수정이 없다

직접 tsc 재빌드 **EXIT2**:

```text
src/gjc-configuration-store.ts(222,15): error TS2339:
Property 'reserveGjcIntent' does not exist on type 'GjcConfigurationAuthorityDb'.
```

`reserveGjcDispatchFromTask`가 선언된 상위 클래스에서 하위 클래스 메서드를 참조한다. `jarvis-tsc.log`에 원문 보존. tsc는 오류가 있어도 JS를 emit했으므로 emit 산출물을 성공 빌드로 간주하지 않았다.

제출 dist와 진단 emit이 다른 파일은 `src/cli-gjc-commands.js`, `src/gjc-configuration-store.js`, `src/gjc-intent-store.js`, `tests/integration/gjc-dispatch-assemble.test.js`다. **4개 모두 제출 dist가 이전37b034f와 바이트 동일**하다 (`dist-difference.json` SHA256). 새 config fence/reservation 코드가 제출 dist에는 없다.

실제 제출 dist의 public `executeGjcCommand`에서 합성 철회 key/config를 사용하면 production fence 단독은 `MEMORY_READ_FENCE_KEY_UNAVAILABLE`, dispatch는 **sends1/oktrue**다 (`gjc-fence-confirmation.json`). 이전 리뷰의 결함이 제출 실행물에서 계속된다. `db.gjcIntentHasEvent` 새 메서드도 제출 dist에 없다. 설치 게이트 EXIT0만으로 새 수정을 verified라 쓰면 안 된다.

완료 기준: 올바른 클래스/타입 계약으로 컴파일 EXIT0을 확보하고 깨끗한 후보를 만들며 source→dist 바이트 대응과 실제 설치 후보의 새 회귀를 함께 확인한다. 오래된 dist 복사로 실패를 덮지 않는다.

## N1-failed-reservation-recovery (P1): 소스 진단에서도 정정 후 재시도가 막힌다

새 소스의 동작을 미리 진단하기 위해 **tsc 오류 중 emit된 JS를 별도 `jarvis-rebuild`에서만** 실행했다. 이것은 제출 dist 결과도, 성공 빌드 인수도 아니다. 정상/실패/복구 계약을 한 번에 고치기 위한 추가 재현이다.

`dispatch-recovery-rebuilt.json` 실제 public handler/합성 DB 결과:

| 시나리오 | 첫 호출 | 정정 후 같은 작업 재시도 | 총 send / model_dispatched |
|---|---|---|---|
| 권한 callback deny→정상 허용 | CURRENT_READER_DENIED | oktrue, duplicate | 0 / false |
| transport2회 거부→정상 transport | MODEL_TRANSPORT_UNAVAILABLE | oktrue, duplicate | 2 / false |
| options 없음→정상 설정 | MEMORY_REFERENCE_OPTIONS_REQUIRED | oktrue, duplicate | 0 / false |

`cli-gjc-commands.ts:95-102`가 preflight/send 전에 pending 예약을 남긴다. 실패를 정리/구분하지 않으며 `gjc-intent-store.ts:34-45`는 pending을 즉시 duplicate로 반환한다. 실제 전송에 성공하지 않았는데 정정 후 같은 경로가 다시 전달하지 않는다. DB public claim으로도 pending이 남아 있는 것을 확인했다. duplicate 응답 자체를 전달 완료로 과장하지 않더라도 정상 정정/재실행의 목표는 미충족이다.

진단 emit에서 config 철회 sends0, 정상 sends1, 동시 같은 키 sends1로 개선된 범위는 보존한다 (`gjc-fence-confirmation-rebuilt.json`, `gjc-lifecycle-rebuilt.json`). 그 개선을 없애지 않으며, durable 예약/현재 worker 소유권/전송 전 거부/명확한 전송 실패/불명확한 결과/재시작 복구를 한 lifecycle로 연결해야 한다. 실패 호출 후 단순 pending duplicate로 종료하지 않는다. task/session·context payload 결합과 기본 실제 설정 경로도 기존 N1 완료 기준 그대로다.

재현:

```bash
TMPDIR=/var/tmp node /var/tmp/codex-night-399cc45-wh2i5plf/gjc-fence-confirmation.mjs
TMPDIR=/var/tmp node /var/tmp/codex-night-399cc45-wh2i5plf/dispatch-recovery-rebuilt.mjs
```

원본 산출물을 보존하려면 harness 복사본에서 실행한다. 재빌드 harness의 migrations/resource 연결은 합성 DB 초기화에 필요한 제품 정적 파일이며 실제 authority/config/auth 복사가 아니다.

## 직접 통과한 범위와 검사 한계

- SB 변경/rollback-focused pytest **14 passed,0.61s**, Ruff EXIT0. Python 변경 파일 타입 **0errors/2warnings,EXIT1** (`os.write` 반환 미사용52/144행). 타입 완전 통과 아님.
- 후보 installed standard/work/maintenance 3게이트 EXIT0. `installed-*.log`은 실제 이번 직접 실행. 단, JARVIS가 오래된 JS이므로 새 N1 수정 인수로 쓰지 않는다.
- N3: 실제 별도 프로세스 writer를 marker 교체 직전에 유지한 동안 reader가 같은 lock에서 busy, 해제 후 writer성공/reader key:a,key:b. 별도4 writer×8회 누적 후 전체34key 보존 (`lock-processes.py/.json`). 단순 lock filename 존재 테스트보다 넓은 직접 검증이다.
- marker dangling/기존 symlink/디렉터리, 부분/완전줄 유실 안전 거부, marker 교체 중단→journal recovery/재시도 기존 harness 통과 (`extended-result.json`, `partial-truncation.json`, `marker-lifecycle.json`). 이전 race harness의 대기 방식을 수정 없이 사용하지 않았다.
- V2 혼합 실패/성공 cap2 calls2, cap1 success calls1 확인 (`extended-result.json`). 이전 범위 로그를 새 전체 인수로 바꾸지 않는다.
- callback 경로 invalid dispatch sends0/재시도 전 철회 sends1 뒤거부 및 factory 정상/실패/만료/no_data 결과는 이번 **제출 dist**에서 직접 확인 (`dispatch-boundaries.json`, `factory-session.json`). config 기반 문제는 위와 같이 남는다.
- Grok 원본 `/var/tmp/sb-full-pytest-f94d073.log` 읽기: **1831passed,2skipped,618.07s,EXIT0**. SHA256 `f2f463820e92ed1a4b2a2aff920fecc87fb501641525a40bd71e3a45eeeebc48`. 이는 기존 전체 로그 관찰이며 Codex 전체 회귀 재실행 수치가 아니다.

초기 harness에서 새 dist API를 예상했으나 없어서 TypeError, 새 예약 동작을 기다렸으나 old dist라 unsettled-await EXIT13이 발생했다. 이를 별도 제품 결함 수로 세지 않았다. 진단 재빌드의 초기 migrations 미연결 역시 harness 오류로 정정했다. 원본 로그/진단 결과를 분리했다.

## M6/M12 미완료는 운영 승인 대기로 넘기지 않는다

이번 패키지는 M6 writer 배제 미입증, M12 cold DR 후 일반 쓰기 미완을 명시한다. 외부 입력만 남은 상태가 아니므로 후보 준비 goal을 끝내고 review 왕복을 반복할 근거가 없다.

추가 직접 fixture 결과: `generation_writer(...,blocking=False)` 두 번째 프로세스는 첫 writer의 `preparing` 중 **busy**, 격리 첫 프로세스 SIGKILL 후 **acquired**. 이는 기존 generation writer helper의 배제/커널 해제만 입증한다. 패키지의 두 번째ok 재현만으로 전체 제품 writer 결함이라고 단정하지 않는다. 그 재현의 lock/path/시점을 확인하고 실제 통합 writer 진입점→실패한 전환→같은 권한/철회 상태의 안전 복구까지 이어서 검증해야 한다.

`/var/tmp/w3-f94d073-rollback.log`는 revocation_store_presentfalse이며 previous_release가 새 후보 자체다. EXIT0은 **철회 상태가 있는 구버전 rollback 안전성 인수**가 아니다. 이전 런북/fixture로만 작업하고 운영 drain/전환은 실행하지 않는다.

M12: `CODEX-NIGHT-REVIEW-7d97af7`의 JARVIS 삭제→복원→2클라이언트/독립철회→재삭제→재복원 통과는 보존한다. 남은 재현은 새 격리 fixture에서 검증된 backup과 허용된 복구 자료만 남기고 원본/제어 DB 부재를 재현→복원→일반 업무의 실제 쓰기/읽기→철회된 자료 부활 없음→RPO/RTO 기록이다. 운영 원본이나 인증을 복사/삭제하지 않는다. 기존 M11 정정/샘플 RSS, N2 검색, N4 실제 UI 실패→정정→pages1 증거도 이전 고정 트리에 한정해 보존한다.

원 A–F, CURSOR-HANDOFF7절 M1–M14의 의미/범위를 유지한다. M1/M2/M5/M8 실제 사용자/native 세션, 운영 drain, 사용자 질문 등의 진짜 외부 입력은 정확히 따로 기록하고 아침 보고로 모은다. 인증 없는 독립 검증을 그 대기로 막지 않는다. M14는 기존 범위를 넘겨 새 기능을 추가하지 않는다.

## 다음 행동

기존 Grok가 현재 승인된 native 목표로 **빌드/실행물 대응 + dispatch 정상·실패·정정·재시작 + M6/M12 통합 근거**를 끝낸 뒤 하나의 일관된 새 후보를 제출한다. 실패한 타입 빌드/옛 dist 또는 실행 가능한 통합 작업을 남겨 놓고 작은 패치마다 ready로 멈추지 않는다. 기존 Codex 감시 작업이 새 고정 후보를 독립 검증한다. 30분 감시 유지, 최종 인수/운영 승인 없음.
