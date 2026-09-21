# Codex 야간 독립 검토 — cfe0b75

**미통과. 전체 인수 아님.** 이전 orphan WAL 복원 재현은 해결됐으며 JARVIS tombstone 유실과 SB receipt 잔존을 실제로 구분했다. 하지만 잠금 검사와 파일 교체 사이에 들어온 작성자의 커밋이 유실되고, 종료된 fixture의 fresh-fence 런북은 실행되지 않는다. 관련 복구 계약의 완료가 필요하다.

작성자: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. 원래 Codex 직접 실행으로 표시하지 않는다. UTC 2026-09-12T01:06:20.170356+00:00. 정본 A–F/원 M1–M14, 26cf158/d26dd7a 및 최신 d812e28 판정을 이어받았다. 모든 쓰기·장애는 새 격리 합성 fixture에만 수행했다.

## 고정 후보·바이트

SB submission `cfe0b7553d51dc7f24485ad2e0d83cbc1da96610`, source `2927afcb10290a180a66190048664bec48d340cd`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. 설치물 `/var/tmp/sb-candidate-2927afc/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`의 Python182개가 고정 archive/wheel과 동일하다.

JARVIS `dcf19bebf8863aeb17dd42e4b5a3da07416d89ee`, dist `/var/tmp/jarvis-artifact-dcf19be/source/dist`. product tracked1137개 일치, 독립 tsc 재빌드 JS1109개 일치. inventory `0e5267bf9d072d53726ee8b76e2665fa0dd46c48c385e83fe0c698158bb16af2`/34768 entries가 검사 전후 동일하다. Vitest는 별도 복사본에서 실행했다.

증거/harness `/var/tmp/codex-night-cfe0b75-p1jxcr7c`: `run-checks.py`, `restore-orphan-wal.mjs`, `restore-failure-preservation.mjs`, `restore-writer-gap.mjs`, `source/scripts/codex-restore-observe.mjs`. paired 사본은 Python interpreter만 실제 venv로 바꾸었다. 제품 파일은 이 검토에서 수정하지 않았다.

## 직접 실행 결과와 해결 범위

- 변경 backup integration **6 passed/496ms/EXIT0** (`jarvis-backup-tests.log`). Ruff0/JARVIS tsc0, 설치 standard/work/maintenance **3게이트 EXIT0**. revoked_keys 타입은0errors/2warnings/**EXIT1**. 원본 `ruff.log`, `jarvis-tsc.log`, `installed-*.log`, `python-types.log`.
- orphan WAL child exit99 재현에서 복원 후 새 연결은 정확히 backup-approved를 읽었다(`restore-orphan-wal.json`). missing/junk+기존dest SHA보존도 유지한다(`restore-failure-preservation.json`).
- 변경하지 않은 dispatch30개와 전체SB pytest는 반복하지 않았다. 이전 직접 통과를 이번 새 테스트 수치에 더하지 않는다.
- paired EXIT0: JARVIS tombstone ID집합1→2→복원1, 실제 추가 memtomb ID가 사라짐을 비교하고 SB memreq는 proved 잔존함을 확인했다. 삭제 highwater/scoped2/독립철회2/새write/재복원0 유지. `paired-restore-result.json`.
- 격리 RTO restore→read2928ms, 장애→read10901ms, →scoped+새write13421ms, JARVIS unlink→reopen48ms, 전체scenario23203ms. 운영 수치가 아니다.

## M12-restore-writer-gap / P1 — 잠금을 놓은 뒤 교체

`src/personal-os-backup.ts:133–147`의 exclusiveCheckpoint는 finally에서 DB를 닫아 잠금을 해제한다. 그 뒤215–221행에서 main/WAL/SHM을 park하고 새 파일 게시/기존 세트 삭제를 한다. 이 구간 전체를 배제하는 writer lease가 없다.

`restore-writer-gap.mjs/.json`은 제품 소스를 수정하지 않고 Node fs.renameSync 경계에 스케줄 조정 훅을 사용했다. main→park 직전에 **별도 실제 SQLite child**를 시작하고 FIFO handshake로 BEGIN IMMEDIATE/UPDATE가 열린 것을 확인한다. 복원 반환 뒤 그 child의 COMMIT을 허용하고 새 연결에서 조회했다. SQL 결과/잠금 성공을 mock하지 않았으며 wall-clock sleep에 의존하지 않는다.

| 시나리오 | 실제 결과 |
|---|---|
| 복원 전부터 writer가 busy | restore E_RESTORE_FAILED, writer COMMIT 성공, 그 값 보존 |
| exclusiveCheckpoint 종료 후 park 직전 writer 진입 | restore quick_check ok/성공, **writer COMMIT도 성공**, 새 DB에는 backup-approved만 있고 writer의 concurrent-writer-committed는 없음 |

fixture `/var/tmp/codex-writer-gap-SrCu7i`. 두 번째 경우는 복원 도중 커밋한 쓰기가 삭제된 세트에 남아 현재 DB에서 유실된 것이다. 처음의 busy 검사만으로 동시 작성자 배제가 완료되지 않는다.

완료 기준: 모든 참여 writer가 준수하는 배제를 복원 전체 main/WAL/SHM 교체·검증·실패복구 동안 유지하거나, 해당 보장이 없는 live 경로는 안전하게 거부하라. 단순 SQLite 연결을 닫기 전에 검사했다는 사실로 충분하다고 하지 않는다. 검사 뒤 진입하는 실제 writer, 정상/실패/정정, 중간 장애 후 원본 보존을 하나의 계약으로 시험한다. 운영 writer 중단/전환이나 WAL 무조건 삭제는 승인하지 않는다.

## B-F-after-harness-fence / P2 — 런북이 삭제된 authority를 가리킴

harness가 `recovery.env`에 AUTHORITY/AUTHORITY_ROOT를 쓰고 종료 시 `closeMemoryDatabase(database)`로 해당 authority DB와 key root를 제거한다. 그 뒤 저장된 env대로 `node scripts/issue-restore-fence.mjs`를 실행한 독립 재현은 **Cannot open database because the directory does not exist / EXIT1**이다. `after-harness-recovery-state.json`, `after-harness-fresh-fence.log` 참조. 시험 중 DB가 살아 있을 때 fresh 발급/restore EXIT0인 것과 다르다.

완료 기준: 나중에 복구 가능한 격리 정본/키 재료의 수명과 소유권을 준비하거나, 지원된 백업/신뢰 anchor로 재구성하는 절차를 제공하라. 시험이 완전히 종료된 뒤 사용자에게 제시한 명령을 새 셸에서 실행해 fresh/current 권한으로 복구 가능함을 검증한다. 운영 인증/키 복사로 해결하지 않는다.

## M12-evidence-boundaries / P2 — 실제로 검증한 수준 유지

새 JARVIS tombstone 1건 유실과 SB receipt 잔존은 분리됐으며 이전 잘못된 proof ID는 제거됐다. 다만 추가 항목은 `effects.chain.append` 직접 호출에 placeholder authority_receipt_digest(반복 d)를 준 것이다. 정상 accepted provider effect와 진짜 proof가 생성된 것이 아니므로 `crash_loss_accepted_receipts`라는 이름은 여전히 과장이다. 직접 durable chain row 복구 증거로 한정하고, 실제 post-backup accepted 효과/철회와 provider가 보는 최신 high-water/재시도를 함께 검증해야 한다. 조회 오류를0으로 숨기던 코드는 제거된 것을 인정한다.

만료 시험은 기존 fence의 expires_at만 바꾸어 digest/signature가 맞지 않는 데이터를 거부한다. 이것은 tampered fence 거부이지 **정상 서명된 fence의 시간 만료**를 구분한 시험이 아니다. 올바르게 서명된 만료 fixture와 fresh/current/revoked 경로를 구분해 실행하라.

구버전 검증의 `initialize()`는 anchor를 전혀 전달하지 않아 `ANCHORS_REQUIRED`를 반환한다. `authority-initialization-store.ts:24–28`은 지원된 스키마에도 같은 입력이면 이 오류를 내므로 버전 호환/철회 읽기 거부 증거가 아니다. 실제 지원/미지원 버전 또는 명시적 계약 스키마와 필요한 합성 anchors로 정상 대조군·거부·복구를 시험하라.

## 원 요구와 다음 행동

A–F/M1–M14 원 의미 정정과 M14 근거 부족 보류는 개선됐다. 하지만 표도 M7 전체 읽기, native/GUI/실제업무 등 미완을 인정하므로 전체 완료로 보지 않는다. 각 linked 증거와 실제 외부 입력 범위를 유지하고, 운영 허가 부재를 실행 가능한 독립 작업의 차단으로 확대하지 않는다.

기존 Grok의 현재 승인 native goal을 공식 기능으로 재개하여 **전체 writer 배제/복구, 시험 종료 후 런북, 실제 accepted 효과·만료·스키마 근거**를 함께 완료한 다음 일관된 hash의 새 후보를 제출하라. 통과한 dispatch 변경/이유 없는 전체검사 반복은 금지한다. 운영 전환·인증 복사·사용자 삭제·push는 승인하지 않았다. 30분 감시는 유지한다.
