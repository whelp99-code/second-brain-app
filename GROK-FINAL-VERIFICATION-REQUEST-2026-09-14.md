# Codex/Claude 최종 검증 요청 — 2026-09-14

**제품 인수 아님. SB 운영 전환은 2026-09-15 완료. JARVIS 미전환. 인증 복사 없음. 실사용자 삭제 없음. 신규 push 없음.**  
Ready는 핸드오프다. Composer 적대검증은 중간 참고이며 이 요청을 대체하지 않는다.

정본: `GROK-REVISED-DEV-PLAN-2026-09-14.md`, `CURSOR-HANDOFF-2026-09-10.md` §7, `GROK-INTEGRATED-COMPLETION-HANDOFF-2026-09-11.md`.

Codex/Claude는 **이 문서의 핀과 로그**만 검증한다. `f7c1945`/`e13cd3b`/`1672626`/`harness-36`/`7d97af7`를 승계하지 않는다.

## 1. 핀

| | |
|---|---|
| SB 브랜치 | `codex/shared-memory-completion-20260907` |
| SB HEAD (docs+leftover) | 이 요청서 작업본 커밋 (베이스 `365f8e4`) |
| SB 제품(후보 source) | `8d1f8cc` |
| 후보 | `/var/tmp/sb-candidate-8d1f8cc/releases/2ccf0267e52da2482d215b1e47dc6bf3f0fbd0e3` |
| wheel_sha256 | `60d66ad6c3d488af843e7132eea2d7104528fb9b0c06ce732d110a2f4ca189f1` |
| JARVIS N1 git | `4d76572` `fix: classify model transport failures on public dispatch` (**로컬, origin 미푸시**) |
| JARVIS N1 dist | `/var/tmp/jarvis-artifact-n1-20260914` |
| JARVIS 원 핀 dist | `/var/tmp/jarvis-artifact-64715ba` (N1 없음. M12 DR는 이 dist) |
| 운영 SB current | `2ccf0267e52da2482d215b1e47dc6bf3f0fbd0e3` (2026-09-15 전환, 제품 `8d1f8cc`). 이전 `41f0751…` 보존 |
| 운영 JARVIS authority | `a3cbbbe1604798052db6051a8751f039573eb126` **미전환** |
| production_activated | SB `true`, JARVIS `false` |
| Claude Code | 2.1.270 |

게이트:

| 게이트 | 로그 | 결과 |
|---|---|---|
| maintenance | `/var/tmp/sb-gates-8d1f8cc-2026-09-14.log` | `maintenance_exit=0` |
| integration (64715ba/dist) | 동일 로그 `integration_sqlite_exit=0` | valid proved, 철회/만료 분기 기대대로 |
| `--work` (N1 dist) | `/var/tmp/sb-gates-work-n1-2026-09-14d.log` | `WORKD_EXIT=0`, work=`REAL-WORK-ITEM-2026-09-10.json` |

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
| N1 테스트 | unit+postcompact+dispatch 40 passed. F2 4 failed는 아래 잔여. N1이 만든 실패 아님 |
| §10 | 31 passed. 상위 디렉터리 교체 반례 미추가 |
| R1 A | `test_compiled_marker_recovery.py` 8 passed |
| R2 B | `test_revoked_keys.py` 11 passed |
| R3 M6 | `/var/tmp/m6-writer-cutover-2026-09-14b.json` EXIT 0 |
| R4 M12 | `/var/tmp/m12-dr-8d1f8cc-2026-09-14.log` EXIT 0 (64715ba/dist) |
| R5 M7 | memory_access+web+scoped_read_policy 36 passed |
| R6 M11 latency | `/var/tmp/m11-latency-8d1f8cc-2026-09-14.log` 30p p50=0.0566 p95=0.0968; 100p 0.0867/0.0977; 300p 0.1628/0.1974. 서버 RSS null. 정정 후 stale 0 |

## 3b. JARVIS 잔여 F2 (미해결, N1 탓 아님)

`tests/integration/gjc-dispatch-assemble.test.ts` **4 failed** at both `64715ba` and `4d76572` (40 passed / 4 failed). 기대 `memory_ref` 8-hex (`12345678`, `87654321`), 실제 `sbrecord:v1:…` (`64715ba` `record_digest` 이후). 기각하지 않음. 수정은 테스트 기대 vs 계약 판단 후 **별도 일반 항목**.

| 테스트 |
|---|
| binds each selected record to its own memory_ref |
| binds distinct records that share body and source to different evidence |
| keeps same-source different-body records on separate lineages |
| persists the same selected memories that the transport sends |

## 4. A–F / M1–M14

| ID | 상태 | 근거 / 남음 |
|---|---|---|
| A | implemented_unverified | R1 8 passed. 운영 원본 세트는 입력 |
| B | implemented_unverified | R2 11 passed. 운영 키 복사 금지 |
| C | implemented_unverified | 검색 계약 기존. N1은 `4d76572`+N1 dist. JARVIS F2 잔여 |
| D | implemented_unverified | 실사용자 1건은 입력 |
| E | implemented_unverified | M12 DR 0, M13 Chrome 0. 운영 GUI timer는 전환 후 |
| F | implemented_unverified | 운영 SB current `2ccf0267…` (2026-09-15). `production_activated(SB)=true`. JARVIS 미전환. `CLAUDE-CUTOVER-2026-09-15.md` |
| M1 | implemented_unverified | 운영 로그인 `blocked_external` |
| M2 | implemented_unverified | 실무 원문 `blocked_external`. `GROK-M2-M4-LINEAGE-CHECKLIST-2026-09-14.md` |
| M3 | implemented_unverified | 열린연결·옛백업 `blocked_deferred` |
| M4 | implemented_unverified | 실무 계보 입력. 항목표 동일 |
| M5 | blocked_external | `GROK-M5-COPY-POLICY-2026-09-14.md` |
| M6 | implemented_unverified | SB 유닛 전환 완료(`2ccf0267…`, 세대 `c58f6026…`). JARVIS 미전환. `CLAUDE-CUTOVER-2026-09-15.md` |
| M7 | implemented_unverified | 36 passed. 운영 원문 세트 입력 |
| M8 | blocked_external | `GROK-CLIENT-CONNECTION-READINESS-2026-09-14.md`. 수집기 ≠ 주입기 |
| M9 | implemented_unverified | SB 훅 `verified_isolated_native (manual compact, 1 session)` `CLAUDE-NATIVE-COMPACT-PROBE-2026-09-15.md`. auto-compaction 미관측. JARVIS 이벤트 없음. 운영 미전환 |
| M10 | blocked_external | 한글 gold |
| M11 | implemented_unverified | p50/p95 측정 + pin-blocks-publish 1 passed. 서버 RSS 미계측. 운영 규모 아님 |
| M12 | implemented_unverified | 격리 DR EXIT 0. 운영 RPO 승인 없음 |
| M13 | implemented_unverified | Chrome 전체 수명 EXIT 0. 운영 timer·삭제경합 deferred |
| M14 | measured_deferred | 고정 질의 extra recall 0. hybrid 기본 off. 새 그래프 없음 |

`blocked_deferred`: 보안 경계, symlink/FIFO, 삭제 경합, 삭제 전 백업 수명. 목표에서 삭제하지 않음. 재시도·이전 금지.

## 5. 검증자에게

1. 운영 current를 바꾸지 마라. push하지 마라.
2. SB 후보는 `8d1f8cc`/`2ccf0267…`. leftover 테스트·문서는 `365f8e4`.
3. N1 검증은 `4d76572`와 `/var/tmp/jarvis-artifact-n1-20260914`. M12 DR는 원 `64715ba` dist. 섞지 마라.
4. `--work`는 N1 dist 로그를 본다. 64715ba 통합 로그의 초반 ENOENT는 artifact 누락이며 최종 `integration_sqlite_exit=0`이 유효하다.
5. M9 SB 훅을 JARVIS M9로 읽지 마라.
6. M14 측정을 hybrid 채택으로 읽지 마라.
7. 보류 분기를 재실행하지 마라.
8. maintenance/integration/`--work`가 실패면 이 후보를 합격으로 쓰지 마라.
9. JARVIS F2 4 failed를 N1 회귀로 읽지 마라. 잔여로 유지하라.

부록: `GROK-CLIENT-CONNECTION-READINESS-2026-09-14.md`, `GROK-M5-COPY-POLICY-2026-09-14.md`, `GROK-M2-M4-LINEAGE-CHECKLIST-2026-09-14.md`, `GROK-M9-JARVIS-NO-EVENT-2026-09-14.md`, `COMPOSER-ADVERSARIAL-REVIEW-2026-09-14.md`.
