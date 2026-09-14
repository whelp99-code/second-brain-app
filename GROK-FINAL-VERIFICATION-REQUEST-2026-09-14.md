# Codex/Claude 최종 검증 요청 — 2026-09-14

**제품 인수 아님. 운영 전환 없음. 인증 복사 없음. 실사용자 삭제 없음. 신규 push 없음.**  
Ready는 핸드오프다. Composer 적대검증은 중간 참고이며 이 요청을 대체하지 않는다.

정본: `GROK-REVISED-DEV-PLAN-2026-09-14.md`, `CURSOR-HANDOFF-2026-09-10.md` §7, `GROK-INTEGRATED-COMPLETION-HANDOFF-2026-09-11.md`.

Codex/Claude는 **이 문서의 핀과 새 게이트 로그**만 검증한다. `f7c1945`/`e13cd3b`/`1672626`/`harness-36`/`7d97af7`를 승계하지 않는다.

## 1. 핀

| | |
|---|---|
| SB HEAD (docs) | `9d2041f` |
| SB 제품 | `8d1f8cc` |
| 후보 | `/var/tmp/sb-candidate-8d1f8cc/releases/2ccf0267e52da2482d215b1e47dc6bf3f0fbd0e3` |
| wheel_sha256 | `60d66ad6c3d488af843e7132eea2d7104528fb9b0c06ce732d110a2f4ca189f1` |
| JARVIS git | `64715ba` |
| JARVIS artifact | `/var/tmp/jarvis-artifact-64715ba` (`runtime`은 64715ba 소유 디렉터리. 예전 `78e7307` 심볼릭 제거. lockfile `0378edb0a0b3c2f8` = git 64715ba) |
| 운영 SB current | `41f0751aca8906d612961e704bc60dd0855fdabd` **불변** |
| 운영 JARVIS authority | `a3cbbbe1604798052db6051a8751f039573eb126` **불변** |
| production_activated | false |
| Claude Code | 2.1.270 (observed 2026-09-14) |
| 3게이트 로그 | `/var/tmp/sb-gates-8d1f8cc-2026-09-14.log` — maintenance_exit=0, integration_sqlite_exit=0. 초반 실패는 artifact config/undici/better-sqlite3 누락. `--work`는 검증된 원문 파일 없어 미실행 |

N1 소스 변경은 **Orca-JARVIS 작업 트리**에 있다. 64715ba dist는 그 변경을 포함하지 않는다. 검증자는 dist와 작업 트리를 섞지 마라.

## 2. 이번 라운드가 한 일

| 항목 | 결과 |
|---|---|
| JARVIS runtime 정합 | PASS. 심볼릭 제거, lockfile=64715ba, `bin/jarvis --help` EXIT 0 |
| N1 | 구현: `CommandModelTransport` `known_not_sent`/`explicit_negative`/`unknown`, unknown 재시도 없음, assemble_context에 `MEMORY_MODEL_TRANSPORT_REQUIRED`. unit+postcompact+dispatch 40 passed. **사전 존재** 4 failed: `memory_ref` hex vs `sbrecord:v1:` (64715ba record_digest). 이번 N1이 만든 실패 아님 |
| §10 | 기존 테스트 31 passed (`opencode` 안정성, inbox ack, connectors inbox, A compile). 상위 디렉터리 교체 반례는 이번 미추가 |
| R1 A | `tests/test_compiled_marker_recovery.py` 8 passed. `USER_EDIT_KEEP_THIS` 단언 유지. 6FB150B 재구현 없음 |
| R2 B | `tests/test_revoked_keys.py` 11 passed |
| R3 M6 | 재실행 EXIT 0. briefing cap 0. `busy_while_held=true`, SIGKILL 후 needle wiki 존재, status=ok. `/var/tmp/m6-writer-cutover-2026-09-14b.json` |
| R4 M12 | `node scripts/jarvis-restore-acceptance.mjs` × 64715ba/dist **EXIT 0**. `/var/tmp/m12-dr-8d1f8cc-2026-09-14.log` |
| R5 M7 | `test_memory_access`+`test_web`+`test_scoped_read_policy` 36 passed |
| R6 M11 | overlap during-compile 유지. 후보 MCP latency `/var/tmp/m11-latency-8d1f8cc-2026-09-14.log` EXIT 0: 30p p50=0.0566 p95=0.0968; 100p 0.0867/0.0977; 300p 0.1628/0.1974. 서버 RSS null. 정정 후 stale 0. **별도 pinned-read-during-publish 테스트는 없음** |
| R7 M13 | conflict 대기 문구 수정 후 Chrome EXIT 0. `conflict_fail=true`. `/var/tmp/m13-gui-conflictfix.log` |
| R8 | maintenance 0. integration 64715ba/dist 0. `--work` REAL-WORK-ITEM JSON × N1 dist `/var/tmp/jarvis-artifact-n1-20260914` **WORKD_EXIT=0** `/var/tmp/sb-gates-work-n1-2026-09-14d.log` |

## 3. A–F / M1–M14

| ID | 상태 | 근거 / 남음 |
|---|---|---|
| A | implemented_unverified | R1 8 passed. 운영 원본 세트는 입력 |
| B | implemented_unverified | R2 11 passed. 운영 키 복사 금지 |
| C | implemented_unverified | 검색 계약 기존. N1 consumer 필수화는 JARVIS 작업 트리 |
| D | implemented_unverified | 실사용자 1건은 입력 |
| E | implemented_unverified | M11/M12/M13 잔여 |
| F | implemented_unverified | 후보 8d1f8cc. maintenance+integration 0. `--work` N1 dist 0. 전환 미실행 |
| M1 | implemented_unverified | 운영 로그인 `blocked_external` |
| M2 | implemented_unverified | 실무 원문 `blocked_external`. 항목표 `GROK-M2-M4-LINEAGE-CHECKLIST-2026-09-14.md` |
| M3 | implemented_unverified | 열린연결·옛백업 `blocked_deferred` |
| M4 | implemented_unverified | 실무 계보 입력. 항목표 동일 |
| M5 | blocked_external | `GROK-M5-COPY-POLICY-2026-09-14.md`. 빈 HOME ≠ 미지원 |
| M6 | implemented_unverified | 2026-09-14b EXIT 0. writer 배제+SIGKILL 복구. 운영 전환 허가 없음 |
| M7 | implemented_unverified | 36 passed. 운영 원문 세트 입력 |
| M8 | blocked_external | `GROK-CLIENT-CONNECTION-READINESS-2026-09-14.md`. 수집기 ≠ 주입기 |
| M9 | implemented_unverified | SB Claude 훅 9d2041f 한정 인수. JARVIS compaction 이벤트 없음 고정. native `/compact` 외부 |
| M10 | blocked_external | 한글 gold |
| M11 | implemented_unverified | 후보 MCP p50/p95 측정. 별도 pinned-publish 테스트 없음. 서버 RSS 미계측 |
| M12 | implemented_unverified | jarvis-restore-acceptance 64715ba/dist EXIT 0. 운영 RPO 승인 없음 |
| M13 | implemented_unverified | Chrome remember/run/search/forget PASS. conflict_fail 문구 불일치 EXIT 1. 삭제경합 deferred |
| M14 | not_implemented | 측정 전 hybrid 기본 off |

`blocked_deferred`: 보안 경계, symlink/FIFO, 삭제 경합, 삭제 전 백업 수명. 목표에서 삭제하지 않음. 재시도·이전 금지.

## 4. 검증자에게

1. 운영 current를 바꾸지 마라.
2. 새 게이트 로그가 `GATES_DONE`이고 maintenance/integration/work가 실패면 **이 후보를 합격으로 쓰지 마라.**
3. N1은 `/var/tmp/jarvis-artifact-n1-20260914` vs 원 64715ba dist를 구분하라. 미커밋 작업 트리.
4. M9 SB 훅을 JARVIS M9로 읽지 마라.
5. 보류 분기를 재실행하지 마라.

부록: `GROK-CLIENT-CONNECTION-READINESS-2026-09-14.md`, `GROK-M5-COPY-POLICY-2026-09-14.md`, `GROK-M2-M4-LINEAGE-CHECKLIST-2026-09-14.md`, `GROK-M9-JARVIS-NO-EVENT-2026-09-14.md`.
