# Codex 야간 독립 검토 — 6a1dcc0

**미통과. 최종 인수 아님.** JARVIS 자체 DB 파일 유실→백업 복원은 이번에 실제 시험에 추가되어 통과했다. 그러나 복원 실패 시 기존 대상 DB까지 삭제되는 제품 결함과 실행 불가능한 복구 절차, 원 요구 번호의 의미가 바뀐 상태표가 남았다. 아래를 단일 관련 복구 계약으로 끝내야 한다.

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`; 원래 Codex 직접 실행으로 표시하지 않는다. UTC 2026-09-12T00:05:45.500817+00:00. 정본 A–F와 CURSOR-HANDOFF §7 M1–M14, 26cf158/d26dd7a 및 최신 713e453 검토를 이어받았다. 모든 파괴적 재현은 새 합성 fixture 안에서만 수행했다.

## 고정 대상·동일성

SB submission `6a1dcc09c5b47cb0ea8788ad69103c9c983bb5b3` / source `f921979d53b9bd14a1af6317d2e219c54723e541` / release `0ecdb5617a1fe95697e55366f631ee4373f407b1` / wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. 설치물 `/var/tmp/sb-candidate-f921979/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`. archive/wheel/설치 Python182개 동일.

JARVIS `e7088b3e220698d50c5a4bd8a52e6f9f9283e491` / `/var/tmp/jarvis-artifact-e7088b3/source/dist`. tracked product1137개 일치, 독립 tsc 재빌드 JS1109개 일치. inventory `a833c70b78560c24e237ba9627c29336cfd9ba14db2a453733322bae74ec371f` 34768 entries가 검사 전후 동일하다. Vitest는 독립 복사본에서 실행했다.

증거·독립 harness: `/var/tmp/codex-night-6a1dcc0-dke0kuts`. `run-checks.py`, `restore-failure-preservation.mjs`, `source/scripts/codex-restore-observe.mjs`. 마지막 것은 고정 정본 paired harness에서 interpreter 경로만 이 환경 venv로 바꾼 사본이다. `submission.json`, `sb-identity.json`, `jarvis-identity.json`, `jarvis-inventory-after-proof.json`에 바이트 검증을 보존했다.

## 직접 실행 통과 범위

- 변경된 backup integration **3 passed**,302ms/EXIT0 (`jarvis-backup-tests.log`). 713e453의 dispatch30개는 미변경 영역으로 다시 실행하지 않았다. 과거 직접통과를 이번 실행 수치에 합산하지 않는다.
- Ruff EXIT0 / JARVIS tsc EXIT0. revoked_keys 타입 검사 0errors/2warnings/**EXIT1**로 전체 타입 통과가 아니다.
- 설치 standard/work/maintenance **3게이트 EXIT0**, `installed-*.log`.
- paired restore EXIT0: JARVIS online backup→백업 후 intent추가1→DB 정상 close→fixture DB/WAL/SHM 제거→restore/reopen. 백업/복원 SHA동일, tombstone1 보존, intent1→0 유실 확인. 이전과 달리 JARVIS DB가 계속 살아 있는 시험이 아니다.
- SB journal2 복구, DeleteAlpha0/KeepBeta1, scoped2 및 독립 철회2, 새 write proved, highwater2/재복원0을 유지했다. `paired-restore-result.json`.
- 이 격리 시나리오의 restore→첫read2165ms, 전체 장애구간→첫read8018ms, →scoped+새write10476ms. 시나리오18270ms와 구분한다. 실제 운영 성능/RPO 인수가 아니다.

## M12-restore-failure / P1: 실패 정리가 기존 DB까지 삭제

JARVIS `src/personal-os-backup.ts:141–145`: dest에 곧바로 copy하고 catch에서 무조건 dest를 rm한다. 독립 `restore-failure-preservation.mjs/.json`은 sentinel이 들어 있는 정상 기존 DB에 대해 두 경로를 실행했다.

| 입력 | 결과 |
|---|---|
| 없는 backup + 기존 정상 dest | E_RESTORE_FAILED, **dest가 삭제됨** |
| 비SQLite backup + 기존 정상 dest | E_RESTORE_FAILED, **dest가 삭제됨** |
| 비SQLite backup + 새 dest | 거부, 새 dest없음, backup보존 |
| 정상 backup + 새 dest | quick_check ok, bytes8192, SHA동일 |

기존 dest의 전 SHA는 `c3f43b5a0ee9e66fef1c6742eef4aa577abcccf1906653df2faeec3c9fb034cd`, 실패 후 파일 없음. 특히 없는 backup은 복사조차 안 된 기존 복구 데이터를 catch에서 삭제한다. 모두 `/var/tmp/codex-restore-preserve-yxBDrg` 합성 fixture에서 재현했다.

완료 기준: 정상/손상/유실/기존 대상/동일 경로 및 정정 재시도를 묶어 검증하라. 백업을 확인한 뒤 안전하게 게시하며, 기존 대상은 명시적으로 거부하거나 검증된 원자적 교체 정책을 적용하라. 실패는 기존 대상과 원본을 보존하고 이번 호출이 만든 임시 산출물만 정리해야 한다. 실제 운영 DB로 시험하지 않는다.

## B-F-recovery-evidence / P2: 준비된 명령과 증거가 맞지 않음

1. `scripts/jarvis-restore-acceptance.mjs`는 첫 fence(sequence1)를 trusted-fence.json에 쓰고 나중에 highwater2까지 진행한다. 종료된 같은 fixture에 런북 restore 명령을 직접 적용하면 **TOMBSTONE_SET_STALE / EXIT1** (`runbook-stored-fence.log`). 이는 SB의 올바른 오래된 fence 거부이며 우회하면 안 된다. 최종 현재세대에서 권한 검증을 거쳐 fresh fence를 발급·전달하는 절차가 필요하다. 단순 파일 재사용은 5분 수명 문제도 있다.
2. 런북 BACKUP은 shell 할당만 있고 export가 없으며 DEST는 정의되지 않는다. Node process.env로 그대로 읽는 재현은 **ERR_INVALID_ARG_TYPE / EXIT1** (`runbook-unexported-env.log`). 목적 fixture와 변수 전달을 명시하고 명령 전체를 처음부터 실행 검증해야 한다.
3. `scripts/writer-lease-on-root.py:_queue_depth`가 requests의 모든 일반 파일을 세어 **journal.db를 queue1**로 센다. 직접 fixture는 inbox/pending 모두 비었고 최상위는 journal.db뿐인데 queue_depth1/empty_queuefalse (`runbook-state.json`). generation writer 실제 경합/거부는 인정한다. 큐는 실제 대기 작업/원장 상태로 별도 측정해야 하며 단순 DB존재를 업무로 세면 안 된다.
4. `old_version_refused=E_RESTORE_FAILED`는 junk 텍스트 입력 시험이다. 실제 구버전 또는 SQLite schema 호환/철회 상태 보존 시험이 아니다. 비SQLite 거부의 정확한 이름으로 기록하고, 요구된 구버전 호환 또는 안전 거부/복구를 실제 대상 버전/스키마로 격리 검증하라.

## M12-rpo-scope / P2: 개선된 범위를 정확히 측정

`crash_loss_receipts=1`의 실제 계산 대상은 createGjcIntent로 만든 gjc_intents 행이다. 외부 accepted receipt/전송 결과를 만든 것이 아니다. receipts_at_backup/after_restore의 deletion_proofs는 모두0이며 countReceipts는 조회 오류도0으로 바꾼다. 원장을 잘못 지정하거나 읽지 못한 경우를 정상0으로 숨기지 말아야 한다.

이번 자체 DB 정상 close 후 파일유실/복원은 유효한 격리 증거로 보존하라. 이를 SIGKILL 중 crash/accepted receipt RPO로 확대하지 말고, 요청한 durable accepted receipt/state의 식별자·백업 후 쓰기·장애 전 마지막 기록·복구 후 비교·시스템별 장애 시점을 실제로 측정하라. JARVIS 백업 이후 추가 철회/권한 변경과 원장 재시도도 복구된 stale 상태를 안전하게 거부하는지 같은 복구 계약에서 확인하라. 타임스탬프와 intent count만 바꾸는 패치로 끝내지 않는다.

## requirements-mapping / P2: 원 의미 복원

새 `IMPLEMENTATION-STATUS.md:9–32`가 A권한/B복구/C삭제/D검색/E정정으로 재명명했다. 정본은 **A 원본·사용자 편집·정정 보존 / B 철회 정본·권한·복원 / C 하나의 검색 계약·품질·실제 본문 전달 / D 실제 공유 기억의 수명 / E 가용성·복구·GUI / F 배포 재료와 운영 절차**다.

M1 신원/권한을 운영 drain 허가로, M2 실제 업무 공유 계보를 이전 철회 경로로, M14 관계검색을 운영 전환으로 바꾼 표도 잘못됐다. M4 검증 결과 원계보는 dispatch본문 계보 하나로 전부 대체할 수 없다. M13 전체GUI를 구체적 입력 없이 blocked_external로 선언하지 않는다. 정본 §7의 M1–M14 의미를 그대로 옮기고 각 근거/미구현/실행 가능한 작업/필요한 실제 외부 입력을 연결하라. 운영 허가가 없는 사실을 독립 구현 전체의 blocker로 확대하지 않는다. M14는 요구된 가치·비용·삭제 일관성 평가 후 효과 없는 경우 근거 있는 보류가 가능하며 운영 전환 항목이 아니다.

## 후속 지시와 외부 조건

기존 Grok의 현재 승인 native goal을 공식 기능으로 재개하고 위 안전 복원, 실제 상태 기반 증거, 실행 가능한 최종 런북, 원 요구 상태표를 **한 묶음으로** 완료한 뒤 새 고정 후보를 제출하라. 기존 통과한 dispatch에 불필요한 변경/전체 회귀 반복은 하지 않는다. 실제 native 제품/버전의 인증·세션 compaction·사본 수명, 실사용 질의 정답집/운영규모, 운영 drain/전환 허가는 별도 정확한 외부 조건으로 유지한다. 운영 전환/인증 복사/실제 사용자 삭제/push는 승인하지 않았다. 30분 자동 감시는 유지한다.
