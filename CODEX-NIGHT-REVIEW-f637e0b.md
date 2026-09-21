# Codex 야간 독립 검토 — f637e0b

**미통과. 제품 준비/운영 인수 아님.** 작성: 기존 Codex 감시 작업 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. 원래 Codex가 직접 실행한 검사로 표시하지 않는다. 시각 2026-09-12T03:06:23.164946+00:00.

고정 제출 `f637e0b858bb40cbf329a5248e983d3cf7bc41d0`; SB source `4536718e68d8d65a24e1a459cb845d86f8c191f2`; release `0ecdb5617a1fe95697e55366f631ee4373f407b1`; JARVIS `1672626c5f2b0b06f7fb93c900cf8771536b58cd`. wheel SHA256 `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57`. 후보 `/var/tmp/sb-candidate-4536718/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1`; dist `/var/tmp/jarvis-artifact-1672626/source/dist`; inventory `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd` /34768항목. 실제 바이트를 먼저 맞췄고 검토 결과를 후속 변경에 자동 적용하지 않는다.

## 이전 P1 및 RPO 수정 확인

`restore-races.mjs`는 실제 자식 SQLite writer를 FIFO와 검토 경계 스케줄 훅으로 진입시킨다. 새 대상 COPYFILE_EXCL 직전 다른 writer가 만든 DB는 이제 복원이 거부되고 writer COMMIT과 값이 보존된다. 기존 DB 초기 exclusive COMMIT 뒤 진입은 SQLITE_BUSY다. SQL/COMMIT 결과를 모의하지 않았다. 기존 P1 재현은 해결됐다.

현재 harness는 실제 ExtraLost accepted forget/proof 이후 JARVIS를 다시 복원한다. 체인3→1, 두 후속 tombstone 유실 및 지정 ID 부재를 실제 측정했다. 이는 이전 시간 역전보다 개선됐으며 해당 JARVIS RPO 구간은 인정한다. 그러나 이 복원 뒤 정상 업무 재개가 끝나지 않았다.

## P2 — M12-post-rollback-recovery

실제 paired fixture `/var/tmp/sb-jarvis-restore-qbdeIl`에서 JARVIS를 sequence1 백업으로 복원한 뒤 SB는 최신 삭제 sequence3을 유지한다. 종료 후 보존한 `recovery-authority`도1이므로 `issue-restore-fence.mjs`는 정상 서명된 새 fence1을 발급한다. 발급 EXIT0 자체는 확인했지만, 같은 ROOT와 이 fence로 새 Python 프로세스에서 `scripts/restore-probe.py restore`를 실행하면 **TOMBSTONE_SET_STALE /EXIT1**이다.

보존된 authority/key 및 같은 MCP 경로로 실제 `createProductionMemoryReference(...).reader.read`를 실행하면 KeepBeta, ExtraLostAfterBackup, PostRestore 모두 **MEMORY_REFERENCE_GENERATION_CHANGED**다. 현재 제품의 오래된 철회 상태 거부는 올바른 안전 동작이다. 미충족은 paired 복구 절차와 가용성 계약이며, high-water를 낮추거나 강제로 허용하라는 요청이 아니다.

코드 `scripts/jarvis-restore-acceptance.mjs:230` 이후 authority 손실/복원, `:270` fresh 발급. 이전 검증의2scoped/새write는 이 두 번째 JARVIS 손실 **이전**이고 후속 가용성을 입증하지 않는다. 원본 `after-harness-fresh-fence.log`, `after-harness-fresh-restore.log`, `after-restore-read.mjs/.json`, `paired-restore-result.json`.

완료 기준: 신뢰된 최신 내구 snapshot 또는 검증된 replay/조정 절차로 JARVIS high-water를 안전하게 회복하고, 전체 장애/복원 뒤 fresh 프로세스에서 fence→복원→2scope 정상읽기/철회거부→새 accepted write/재시도를 끝낸다. 필요한 최신 신뢰자료가 없으면 정확한 미충족/보류와 복구 준비 절차를 기록한다. 합성 fixture의 승인/키만 사용하며 운영 인증 복사나 SB high-water 강등으로 우회하지 않는다.

## P2 — M12-recovery-gate-false-positive

`jarvis-restore-acceptance.mjs:243–249`는 두 번째 restore의 모든 오류를 잡아 `blocked_matches:0`인 대체 객체를 만든다. `:274–276`은 복원이 없더라도 `second_restore_records:0`과 이전 scoped 수치를 출력한다. 실제 새 reader 검사가 제거됐다.

검토 복사본 `source/scripts/codex-restore-failure-probe.mjs`에서 extraFence 발급 시각만120초 전으로 바꿨다. **정상 서명된 만료 fence**에 대한 SB 거부 TOMBSTONE_FENCE_REQUIRED가 발생했는데도 harness는 **EXIT0**, fallback sequence1, jarvis_owned_high_water3, second_restore_records0을 반환했다. 이는 검증 harness의 실패 판정 오류이며 제품의 올바른 만료 거부를 제품 결함으로 센 것이 아니다. 원본 `paired-expired-fence-control.log/.json`에 보존했다. 해당 실패 경로 확인을 위해서만 추가 paired 실행을 했고 전체 제품 회귀를 반복하지 않았다.

SB `rpo_sb`의 writes_after_backup_before_failure=1/crash_loss_records=1은 여전히 첫 restored generation을 참조하지만 ExtraLost는 그 뒤 생성된다. 첫 SB복원, 두 번째 SB복원, JARVIS 두 번째복원 각각 시각/실제 request/proof/기록을 분리해야 한다. 두 번째 성공한 sanitation 뒤의 실제 생존 기록도 reader/원장 조회로 측정해야 한다.

완료 기준: 예상 거부 시험과 필수 성공 복구를 분리하고, 필수 복원·읽기·재시도 실패 시 전체 gate를 실패시킨다. 실제 조회로 건수를 산출한다. 준비 조건 부족이면 skipped/blocked/failed를 정직하게 반환하며0건 성공으로 대체하지 않는다. 위 복구 계약 전체와 함께 하나의 후속 후보로 제출한다.

## 직접 검증 및 유지된 통과

- SB archive/wheel/installed182Python byte-identical; manifest/source and wheel SHA checked
- JARVIS1137 tracked product files and1109 emitted JS identical; tsc EXIT0; inventory34768 unchanged
- 8 backup integration tests directly passed;291ms total,53ms tests
- Ruff EXIT0; installed standard/work/maintenance3gates EXIT0
- Actual child SQLite writer created missing dest just before COPYFILE_EXCL: restore refused, COMMIT succeeded and value preserved; previous P1 fixed
- Existing busy writer refusal/preservation and writer entering after exclusive COMMIT SQLITE_BUSY still pass
- Existing clone actual child exit99 after DROP: original preserved; retry restores backup
- Orphan WAL child exit99 restores backup rows; invalid/missing backup preserves existing dest; ordinary new-dest success
- JARVIS actual accepted extra forget now precedes second authority restore: chain3→1 and lost ID absent confirmed; previous JARVIS RPO chronology corrected for this interval
- First paired recovery:2scoped readers/2independent revocations, shared memory and new proved write; later extraFence3 sanitation succeeds using pre-crash fence; no claim of post-JARVIS-loss reader availability
- After-harness fence issue EXIT0 only; follow-on restore/read fail separately as findings

revoked_keys 타입은 **0errors/2warnings/EXIT1**, 완전 통과 아님. 첫 복구 RTO는 restore→read2125ms, failure→read7404ms, failure→업무가능9808ms, 첫 JARVIS unlink→reopen52ms, 시나리오24321ms다. 마지막 JARVIS 손실 뒤 가용성 RTO가 아니다. Grok 자체 제출8tests와 위 Codex 직접8tests를 합산하지 않는다. 기존 변경 없는 SB 전체/dispatch suite는 재실행하지 않았다.

원본 로그: `jarvis-backup-tests.log`, `installed-standard.log`, `installed-work.log`, `installed-maintenance.log`, `ruff.log`, `python-types.log`, `jarvis-tsc.log`, `sb-identity.json`, `jarvis-identity.json`, `jarvis-inventory-before.json`, `jarvis-inventory-after-proof.json`, `restore-races.json`, `restore-crash-transaction.json`, `restore-orphan-wal.json`, `restore-failure-preservation.json`, `paired-restore.log`.

## 요구·외부 조건·다음 행동

원 A–F/M1–M14와 선행 R1–R7/V1–V5의 범위 및 미완료를 유지한다. 실제 native 신원/제품별 연결·전체 읽기표면·compaction·사본수명·실사용 검색정답셋·운영규모·전체GUI와 운영 인수는 합성/직접helper/제품entrypoint 검증과 구분한다. M14 보류가 임의 새 기능 허가는 아니다. 동시작성자 결함이 해결된 범위는 보존하고 불필요한 dispatch 변경을 만들지 않는다.

운영 current41f0751/production_activated=false는 제출 정보다. 새 운영 health 확인이나 운영 전환을 수행하지 않았다. 운영 authority/config/auth 복사, 실제 사용자 삭제, push 없음. Codex 제품 소스/테스트 수정 없음; 검토 harness/보고서/조정 기록만 작성했다.

기존 Grok에 위 통합 검토와 원본 `/var/tmp/codex-night-f637e0b-hldpso0f`를 전달한다. 승인된 현재 native 목표만 이어가고 복구/검증을 묶어 완료하게 한다. 전송/실제 착수/지속은 control에서 구분한다. 사용자 중단 또는 검증된 최종 완료 전까지 기존30분감시 유지.
