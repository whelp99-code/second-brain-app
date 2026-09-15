# Codex/Claude 최종 검증 요청 — 2026-09-14

**제품 인수 아님. SB·JARVIS 운영 전환은 2026-09-15 14:32 KST 완료. 인증 복사 없음. 실사용자 삭제 없음. 신규 push 없음.**  
Ready는 핸드오프다. Composer 적대검증은 중간 참고이며 이 요청을 대체하지 않는다.

정본: `GROK-REVISED-DEV-PLAN-2026-09-14.md`, `CURSOR-HANDOFF-2026-09-10.md` §7, `GROK-INTEGRATED-COMPLETION-HANDOFF-2026-09-11.md`.

Codex/Claude는 **이 문서의 핀과 로그**만 검증한다. `f7c1945`/`e13cd3b`/`1672626`/`harness-36`/`7d97af7`를 승계하지 않는다.

## 1. 핀

| | |
|---|---|
| SB 브랜치 | `codex/shared-memory-completion-20260907` |
| SB HEAD (docs) | `b239c0b` |
| SB 제품 | `83a7aba` |
| 운영 SB current | `8ea65a7d968fdcf99560f449b2a1ad656a99a2e9` (2026-09-15 14:32 KST). 이전 `2ccf0267…`/`41f0751…` 보존 |
| wheel_sha256 | `6bc94e226c0158ab2ee517a344efc3d0c07faddcf75eb27868dafd46d1f965ba` |
| JARVIS git | `65bfd64` (**로컬, origin 미푸시**) |
| 운영 JARVIS authority | `387c7c95509153a49dfac7d1c93c43881e74274e` (source `65bfd64`) |
| control-center current | `artifact-7e8ddde923c2afb1d290e00c2a73d1cc585fe94b6982ae1f8d44f78e83273e5f` |
| jarvis.sqlite migrations | 81 |
| production_activated | SB `true`, JARVIS `true` |
| Claude Code | 2.1.270 |

게이트:

| 게이트 | 로그 | 결과 |
|---|---|---|
| maintenance | `/var/tmp/sb-gates-8d1f8cc-2026-09-14.log` | `maintenance_exit=0` |
| integration (64715ba/dist) | 동일 로그 `integration_sqlite_exit=0` | valid proved, 철회/만료 분기 기대대로 |
| `--work` (ops 387c7c95) | `/var/tmp/claude-night-e53dd66-GBr0la/gates/work-ops-387c7c95.log` | EXIT0, work=`REAL-WORK-ITEM-2026-09-15.json` |

SB leftover 커밋(푸시 없음): `4eff746` pin test, `6c97168` M6/M13 harness, `5899ee4` M14 측정, `365f8e4` 요청서 초판, 이 커밋이 요청서 작업본 고정.

## 2. 네 leftover (이번에 닫은 것)

| 항목 | 커밋/증거 | 결과 |
|---|---|---|
| M13 `conflict_fail` | `6c97168` + `/var/tmp/m13-gui-conflictfix.log` | Chrome EXIT 0. 실패 경로 busy sentinel `정정 중…`. `conflict_fail=true`. remember/run/search/forget PASS |
| pinned-publish | `4eff746` `test_held_pin_blocks_publish_then_omega_is_current` | 1 passed. 핀 동안 `GENERATION_WRITER_BUSY`. 해제 후 현재 세대는 Omega만 |
| N1 dist | JARVIS `4d76572` + `/var/tmp/jarvis-artifact-n1-20260914` | 공개 dispatch consumer 필수, `known_not_sent`/`explicit_negative`/`unknown`. **push 안 함** |
| M14 측정 | `5899ee4` + `/var/tmp/m14-relation-search-2026-09-14.json` | `gateway` → `wiki/deploy`. 한글 관계질의 lexical/hybrid 둘 다 0 extra. **hybrid 기본 off 유지** |

## 3. 그 앞 라운드 재증명 (유지)

| 항목 | 결과 |
|---|---|
| JARVIS 64715ba runtime 정합 | lockfile=git 64715ba, `bin/jarvis --help` 0 |
| N1 테스트 | unit+postcompact+dispatch. F2는 `8745ce7`로 해소(계약 정본). N1이 만든 실패 아님 |
| §10 | 31 passed. 상위 디렉터리 교체 반례 미추가 |
| R1 A | `test_compiled_marker_recovery.py` 8 passed |
| R2 B | `test_revoked_keys.py` 11 passed |
| R3 M6 | `/var/tmp/m6-writer-cutover-2026-09-14b.json` EXIT 0 |
| R4 M12 | `/var/tmp/m12-dr-8d1f8cc-2026-09-14.log` EXIT 0 (64715ba/dist) |
| R5 M7 | memory_access+web+scoped_read_policy 36 passed |
| R6 M11 latency | `/var/tmp/m11-latency-8d1f8cc-2026-09-14.log` 30p p50=0.0566 p95=0.0968; 100p 0.0867/0.0977; 300p 0.1628/0.1974. 서버 RSS null. 정정 후 stale 0 |

## 3b. JARVIS F2 해소

**결정: 계약이 정본, 테스트가 낡음.** SB `memory_records.record_id` = `sbrecord:v1:`+digest64. JARVIS `second-brain-evidence-parser`가 같은 정규식을 요구. `CODEX-NIGHT-REVIEW-069aeaa.md`는 consumer `memory_ref`가 원 `record_id`와 같다고 확인. 8-hex sid는 64715ba 이전 기대값.

해소: JARVIS `8745ce7` (테스트만). 세 파일 **44 passed / 0 failed**. typecheck 0 errors. lint는 파일 기존 unused 경고 유지(이번 변경이 만든 실패 아님). N1 dist 불변. 운영 authority 미변경.

## 4. A–F / M1–M14

| ID | 상태 | 근거 / 남음 |
|---|---|---|
| A | implemented_unverified | R1 8 passed. 운영 원본 세트는 입력 |
| B | implemented_unverified | R2 11 passed. 운영 키 복사 금지 |
| C | implemented_unverified | 검색 계약 기존. N1은 `4d76572`+N1 dist. F2 해소 `8745ce7` |
| D | implemented_unverified | 실사용자 1건은 입력 |
| E | implemented_unverified | M12 DR 0, M13 Chrome 0. 운영 GUI timer는 전환 후 |
| F | verified | 2026-09-15 14:32 KST ops. SB `8ea65a7d…` JARVIS `387c7c95…`. `CLAUDE-CUTOVER-2026-09-15.md` |
| M1 | blocked_external | 운영 로그인 |
| M2 | implemented_unverified | `REAL-WORK-ITEM-2026-09-15.json` `--work` EXIT0. 운영 gjc 종단은 코디네이터 미구성 |
| M3 | verified | H1–H4 `b239c0b` 1924 passed · 운영 `8ea65a7d…` |
| M4 | implemented_unverified | `REAL-WORK-ITEM-2026-09-15.json` `--work` EXIT0. 운영 gjc 종단은 코디네이터 미구성 |
| M5 | blocked_external | 실사용자 native 처분 |
| M6 | verified | writer 배제·복구 실행. `CLAUDE-CUTOVER-2026-09-15.md` |
| M7 | implemented_unverified | 36 passed. 운영 원문 세트 입력 |
| M8 | blocked_external | 타 클라이언트 |
| M9 | implemented_unverified | SB hook `verified_isolated_native (manual)`. auto 미관측. JARVIS 이벤트 없음 |
| M10 | blocked_external | 한글 gold |
| M11 | implemented_unverified | p50/p95 측정 + pin-blocks-publish 1 passed. 서버 RSS 미계측. 운영 규모 아님 |
| M12 | implemented_unverified | 격리 DR EXIT 0. 운영 RPO 승인 없음 |
| M13 | blocked_external | 실사용자 처분 |
| M14 | decided_off | `CLAUDE-M14-DECISION-2026-09-15.md` |

잔여 외부: M1 운영 로그인, M10 gold, M5/M13 실사용자 처분, M8 타 클라이언트. JARVIS F2 해소(`65bfd64`).

## 5. 검증자에게

1. 운영 current를 바꾸지 마라. push하지 마라.
2. 운영 핀은 SB `8ea65a7d…` / JARVIS `387c7c95…`. leftover 문서는 `b239c0b`.
3. `--work`는 `/var/tmp/claude-night-e53dd66-GBr0la/gates/work-ops-387c7c95.log`.
4. M9 SB 훅을 JARVIS M9로 읽지 마라.
5. M14는 `decided_off`. hybrid 채택으로 읽지 마라.
6. H1–H4는 배포됨. 재시도하지 마라.
7. JARVIS F2는 `65bfd64`로 해소.

부록: `GROK-CLIENT-CONNECTION-READINESS-2026-09-14.md`, `GROK-M5-COPY-POLICY-2026-09-14.md`, `GROK-M2-M4-LINEAGE-CHECKLIST-2026-09-14.md`, `GROK-M9-JARVIS-NO-EVENT-2026-09-14.md`, `COMPOSER-ADVERSARIAL-REVIEW-2026-09-14.md`.
