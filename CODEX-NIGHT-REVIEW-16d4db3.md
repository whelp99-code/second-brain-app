# Codex 야간 독립 검토 — 16d4db3

**미통과. 제품 준비/운영 인수 아님.** 작성: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. 원래 Codex가 직접 실행한 검사로 표시하지 않는다. 검토 시각 2026-09-12T02:07:05.881751+00:00.

고정 제출 `16d4db331533915ac47b31ec2b10a2bc9d232e2f`, SB source `d4759bcf67749ada6b3bd354bf48429c8f08a0fb`, release `0ecdb5617a1fe95697e55366f631ee4373f407b1`, JARVIS `b9ccc546ab9d4d537e17918a68eacf4ecb98f94c`. 휠 SHA256 `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. 후보 `/var/tmp/sb-candidate-d4759bc/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`, dist `/var/tmp/jarvis-artifact-b9ccc54/source/dist`. 소스와 산출물을 먼저 대조했고 이 검토를 이후 변경 후보에 자동 적용하지 않는다.

## 통합 결함과 완료 기준

### P1 — 대상 파일이 없던 복원 경로의 작성자 경합

`src/personal-os-backup.ts:228`은 대상 존재를 한 번 확인하고, 없는 경우 `:235`에서 staging을 rename한다. 그 사이 다른 프로세스가 정상 DB를 만들고 쓰면 rename이 이를 덮어쓴다.

`restore-races.mjs`는 검토용 경계 스케줄 훅과 FIFO로 실제 자식 SQLite writer를 진입시킨다. SQL과 COMMIT 결과는 모의하지 않았다. 세 대조군 결과:

- 이미 writer가 잡고 있는 기존 DB: 복원 E_RESTORE_FAILED, writer COMMIT 성공, 쓰기 보존.
- 기존 DB의 초기 exclusive COMMIT 뒤 진입: writer SQLITE_BUSY, 복원 성공, backup-approved. **직전 기존 DB 경합은 해결됐다.**
- 처음에는 없는 대상의 staging rename 직전 다른 writer가 DB를 생성/수정: 복원 성공과 writer COMMIT 성공이 동시에 반환되지만 새 SQLite조회는 backup-approved만 남는다. **승인된 쓰기 유실이 계속된다.**

재현: `node /var/tmp/codex-night-16d4db3-x4w54h5y/restore-races.mjs`. 원본 `restore-races.json`; fixture `/var/tmp/codex-restore-races-43K3C1`. 이는 자연 발생 빈도를 측정한 시험이 아니라 실제 프로세스의 진입 시점을 고정한 경합 재현이다.

완료 기준: 기존 대상/없는 대상 모두 복원 전체에서 소유권과 작성자 배제를 보장하거나 안전 거부해야 한다. 검사 후 생성된 DB를 덮어쓰지 않고 성공한 쓰기를 보존해야 한다. busy/늦은 진입/중간 중단/정정 재시도를 함께 검증한다.

### P2 — RPO의 장애 전후 시간 순서가 뒤바뀜

`scripts/jarvis-restore-acceptance.mjs:82–90`에서 JARVIS를 이미 복원하고 counts/IDs를 저장한다. ExtraLost remember/forget은 `:206–219`에서 그 이후 생성한다. `:296`은 나중 extra count2에서 이전 restore count1을 빼서 crash_loss_accepted_receipts=1로 표시한다. 그 effect에 대한 후속 JARVIS 장애/복원은 없다. SB `writes_after_backup_before_failure=1`도 첫 장애 뒤 쓰기와 혼동한다.

직접 실행한 paired 결과의 claimed lost tombstone은 전체 harness 종료 뒤 보존된 recovery authority에 sequence2로 실제 남아 있다. 생성 시각은 첫 SB복원보다 늦다. `rpo-chronology-proof.json`에 실제 SELECT/시각을 기록했다. 이번 `effects.apply`는 이전 직접 chain append보다 개선됐지만 시간 역전 때문에 실제 crash-loss 증거가 되지 않는다. 최종 두 번째 SB 복원은 별도 구간으로 구분해야 한다.

완료 기준: backup → 실제 accepted write/effect 및 proof → 장애 → 해당 시스템 복원 → 같은 ID 조회를 순서대로 실행하고 시각/원장을 기록한다. 최신 철회 high-water·재시도/조정·부활 방지를 함께 검증한다. SB와 JARVIS 각각 실제 RPO만 표시한다.

## 직접 통과한 범위

- SB182 Python files archive/wheel/installed byte-identical; pinned manifest/source and wheel SHA verified
- JARVIS1137 tracked product files and1109 rebuilt JS identical; tsc EXIT0; inventory34768 unchanged
- 7 backup integration tests directly passed;334ms total,43ms tests; fixture-only
- Ruff EXIT0; installed standard/work/maintenance each EXIT0
- Existing busy writer refused and writer COMMIT preserved; child entering after initial exclusive COMMIT refused SQLITE_BUSY while restore succeeds
- Existing-dest mid-transaction actual process exit99 after DROP preserves original; normal retry restores backup
- Previous orphan WAL exit99 reproduction now returns backup-approved; missing/junk backup retains existing dest; normal new-dest restore passes
- Current synthetic full authority backup restored into an existing synthetic authority successfully; no view collision observed
- Paired harness EXIT0;2scoped readers and2independent revocations,new proved write,high-water3 and second restore0records
- After harness exit, exact issue-restore-fence command using exported preserved authority succeeds EXIT0
- Signed expired fence now issued via authorize(past), refused; corrupted migration checksum gives MIGRATION_CHECKSUM_MISMATCH with synthetic anchors, supported copy opens; limited fixture compatibility evidence

revoked_keys 타입 검사는 **0errors,2warnings,EXIT1**이며 완전 통과로 표시하지 않는다. Grok의 제출된7tests/게이트 로그와 별개로 위 검사는 Codex가 직접 실행했다. 같은 고정 SB 전체 회귀/변경 없는 dispatch suite는 이유 없이 반복하지 않았다.

직접 paired RTO: restore→read 2112ms, failure→read7339ms, failure→업무가능9622ms, JARVIS unlink→reopen45ms, 전체26149ms. 합성 격리 규모이며 운영 RTO가 아니다. 원본 `paired-restore.log/.json`, `jarvis-backup-tests.log`, `installed-*.log`, `jarvis-identity.json`, `sb-identity.json`, `jarvis-inventory-*.json`, `after-harness-fresh-fence.log`, `restore-crash-transaction.json`, `restore-own-schema.json`.

## 범위·외부 조건·다음 행동

기존 A–F 및 원 M1–M14 의미와 미완료 판정을 유지한다. 실제 native 신원/제품별 연동·전체 읽기표면·compaction·사본수명·실사용 검색정답셋/운영규모·전체 GUI/운영 인수는 위 격리 검사로 대체하지 않는다. M14 보류는 임의 새 기능 허가가 아니다. 기존 수정된 V1/V2와 선행 검토 통과는 그 검증 경로에 한정한다.

운영 current41f0751/production_activated=false는 제출 정보이며 이번 운영 health 확인이 아니다. 실제 운영 authority/config/auth를 복사하지 않았다. 제품 소스/테스트 수정, 운영 전환, 사용자 기록 삭제, push를 수행하지 않았다. 새 fixture의 harness/보고서/조정 기록만 작성했다.

기존 Grok에 이 두 결함의 통합 검토를 전달하고 현재 승인된 native 구현 목표를 재개한다. 새 구현자를 만들지 않는다. 구현/자체 검증이 끝난 일관된 새 후보를 재검토하며 30분 감시를 유지한다. 모든 원본 `/var/tmp/codex-night-16d4db3-x4w54h5y`. 착수/지속은 control에 별도 기록한다.
