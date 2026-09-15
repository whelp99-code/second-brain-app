# 최종 검증 요청(2026-09-14) 독립 검증 — 제출 365f8e4 / 제품 8d1f8cc

작성자: Claude Fable 5.1 (Codex 검증 역할). 2026-09-15T00:32:32.614620+00:00. 원본 `/var/tmp/claude-night-e53dd66-GBr0la` (gates/, jarvis/, m*-rerun.*).

**판정: 격리 후보 인계로 인수.** 요청서의 핀·게이트·DR·harness·테스트 수치를 모두 독립 재실행으로 재현했다. 제품/운영 인수가 아니다(native `/compact`, 운영 전환, 실사용자 업무, 한글 gold, 보류 분기, A–F/M1–M14 전체 인수는 외부·보류 유지).

## 핀 확인
- SB 제품 `8d1f8cc` ↔ 후보 wheel `60d66ad6c3d488af…` ↔ 설치본 183파일 일치. `9d2041f..365f8e4`에 sb/deploy/systemd 변경 없음(테스트·스크립트·문서만).
- JARVIS N1 dist `/var/tmp/jarvis-artifact-n1-20260914/dist` = `4d76572` clean 재빌드와 **586 js 파일 0 불일치** (dist 메타데이터는 dirty 64715ba로 기록돼 있으나 바이트 동일). 원 핀 dist `64715ba` 별도 유지. 4d76572는 미푸시.
- 운영 current 불변(SB 41f0751 / J a3cbbbe). 이번 검증에서 운영·auth·push 없음.

## 직접 재실행
| 항목 | 결과 |
|---|---|
| maintenance 게이트 | `MAINT_EXIT=0` |
| integration 게이트 (64715ba dist) | `INTEGRATION_EXIT=0` (proved 1, 철회/만료 failed 2 기대대로) |
| `--work` 게이트 (N1 dist, REAL-WORK-ITEM) | `WORK_EXIT=0` |
| M12 DR (64715ba dist) | M12_EXIT=0; classified_write_after_required_restores=true, shared_restored_memory_equal=true, generic extra_lost=0/keep_beta=0, crash_loss_records=0, restore→readable 2077ms |
| M6 writer 배제 | busy_while_held=true, SIGKILL 후 status ok exit 0, cutover=false |
| M13 Chrome 수명 | M13_EXIT=0; remember fail/ok, run ok, search, conflict_fail=true, discard, forget 후 검색 0 — 전부 true |
| M14 측정 | control `gateway`→wiki/deploy; 한글 관계질의 lexical/hybrid 0 extra; hybrid 기본 off |
| M11 latency (후보 MCP) | 30p p50 0.0507 / p95 0.0801; 100p 0.0799 / 0.0834; 300p 0.161 / 0.189 s. 서버 RSS 미계측 |
| pytest (365f8e4 archive) | mcp_generation 4(신규 pin 테스트 포함), compiled_marker_recovery 8, revoked_keys 11, memory_access+web+scoped_read_policy 36 — 모두 passed |
| JARVIS vitest (4d76572) | 40 passed / 4 failed; 64715ba archive 36 passed / **같은 4 failed** → 사전 존재 확인, N1은 4개 추가 통과 |
| 전체 회귀 | 9d2041f archive 1904 passed / 3 skipped (09-13 직접 실행). 이후 제품 바이트 불변 |

## 조건·잔여
- **F1** (ordinary): GROK-FINAL-VERIFICATION-REQUEST-2026-09-14.md is modified and uncommitted; the frozen submission must be a commit. Commit the working copy (docs only).
- **F2** (ordinary (JARVIS)): 4 JARVIS tests in tests/integration/gjc-dispatch-assemble.test.ts fail at both 64715ba and 4d76572 (memory_ref expected 8-hex ids, received sbrecord:v1:... after the 64715ba record_digest change). Pre-existing, not caused by N1, but it is an open JARVIS test/contract mismatch and must be listed as a JARVIS residual, not dismissed.
- **F3** (note): N1 dist was built from a dirty 64715ba tree before commit 4d76572 existed (build-metadata dirty=true); verified byte-equal to a clean rebuild of 4d76572, so provenance is acceptable. 4d76572 is unpushed (push not approved).
- **F4** (note): M11 script reports server RSS null (not measured); M14 shows no extra recall for the fixed Korean query (hybrid off) - a measurement, not a value decision.

## 외부·보류(변경 없음)
native `/compact` (`/var/tmp/sb-native-probe-8d1f8cc/README.md` 절차 준비됨, 사용자 실행), 운영 전환/writer 배제 허가, 실사용자 task/원문, 한글 gold 100–300, M5/M13 실사용자 처분, 보안/삭제 경합/복원 수명 보류 분기(재시도·이전 없음).

## 후속 확인 (efaec8f)
- F1: 요청서를 docs 커밋 `efaec8f`로 고정(제품 바이트 불변 확인).
- F2: 요청서 §3b와 IMPLEMENTATION-STATUS에 JARVIS 잔여로 기록됨(미해결, N1 탓 아님).

## F2 해소 확인 (2026-09-15)
- JARVIS `8745ce7`(테스트만): memory_ref 기대값을 `record_id`(`sbrecord:v1:`)로 갱신. SB `sb/memory_records.py:217`의 record_id 정의와 일치하므로 계약 정본 판단이 맞음. 네 테스트의 원 의도(record별 고유 ref, 동일 본문·출처 구분, 별 lineage, persisted==sent) 유지.
- 독립 재실행: 3파일 44 passed / 0 failed, `tsc --noEmit` EXIT0. N1 dist 불변, push 없음.
