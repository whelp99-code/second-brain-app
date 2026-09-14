# 적대적 검증 판정 — Composer 2.5 / 2026-09-14

## 1. 한 줄 판정

**조건부 기각.** Grok 잔여 리스트는 원 A–F/M1–M14 범위를 대체로 인지했으나, **이미 한정 인수된 M9(SB Claude hook) 재구현**, **패키징/최종검증자 역할의 게이트 재실행**, **외부입력 항목의 개발 재분류**, **basedpyright·§10 구현 결손 누락**, **CURSOR-HANDOFF M1/M2 우선순위 역전**이 섞여 있다. 살아남는 것은 현재 핀 `8d1f8cc`×`64715ba`에서 **증거 없는 implemented_unverified 실구현**과 **제출물 정합화**뿐이며, 중간 Composer 검증은 역할 전제와 모순된다.

---

## 2. KILL 표

| 항목 | 판정 | 이유 | 근거 |
|------|------|------|------|
| **1 (일부)** | KILL | 후보 `/var/tmp/sb-candidate-8d1f8cc/releases/2ccf0267…` **이미 존재**, manifest `source_commit=8d1f8cc`. `prepare-release` 재실행은 바이트 동일 시 **개발이 아니라 패키징 재증명**이며 Codex/Claude 최종검증자 역할. Grok이 “개발”로 넣은 것은 **WRONG-BUCKET**. | `release-manifest.json:13-16`; `CLAUDE-NIGHT-REVIEW-9d2041f.md:8-9` |
| **1 (일부)** | KILL | `/var/tmp/sb-gates-f7c1945.log`는 **f7c1945/e13cd3b 핀** 증거. `8d1f8cc`×`64715ba` 게이트 로그 **없음**. 옛 로그를 현재 증거로 쓰면 **STALE-PIN** — 리스트는 재실행을 요구하나 “개발”이 아님. | `CODEX-REMAINING-TRIAGE-2026-09-13.md:19`; brief 핀 관측 |
| **11 (SB 부분)** | KILL | M9 Claude Code 2.1.270 `SessionStart(compact)` hook 경로는 **9d2041f에서 한정 인수**(30 tests, probe 17/17). 동일 hook 재구현은 중복. JARVIS compaction 미연결은 **별 항목**이지 SB hook 재작업이 아님. | `CLAUDE-NIGHT-REVIEW-9d2041f.md:5-15`; `GROK-M9-SESSION-COMPACTION-CONSTRAINT-2026-09-13.md:6-12` |
| **17** | KILL | `2n`, `phone-history/`, `.bak` 보존은 **운영 지시**이지 개발 항목. 리스트에 넣은 것은 범위 오염. | `GROK-COMPLETION-CONTINUATION-2026-09-13.md:11` |
| **Grok 제외: M1 실로그인** | KILL(개발목록에서) | 올바른 **WRONG-BUCKET→외부입력** 분류. 재넣을 이유 없음. | `CODEX-REMAINING-TRIAGE-2026-09-13.md:44,97-98` |
| **Grok 제외: M2/M4 task** | KILL(개발목록에서) | 사용자 task ID/원문 없음. 개발 아님. | `CURSOR-HANDOFF-2026-09-10.md:145-147`; triage §5 |
| **Grok 제외: M10 gold** | KILL(개발목록에서) | 100–300 실질문·근거는 **콘텐츠 입력**. | `IMPLEMENTATION-STATUS.md:28`; triage §3 M10 |
| **Grok 제외: F/M6 운영전환** | KILL(개발목록에서) | 사용자 금지 범위와 일치. | brief; `GROK-COMPLETION-CONTINUATION-2026-09-13.md:11` |
| **Grok 제외: M9 native `/compact`** | KILL(개발목록에서) | `M9_native_session`은 **blocked_external**로 명시. | `CLAUDE-NIGHT-REVIEW-9d2041f.md:23`; `GROK-M9-SESSION-COMPACTION-CONSTRAINT-2026-09-13.md:12` |
| **Grok 제외: M5/M13 실사용자처분** | KILL(개발목록에서) | 소유자·처분 허가 필요. 개발 아님. | triage §5:102 |

---

## 3. MISSING 표

| 빠진 원 요구 | 왜 개발/준비인지 | 정본 위치 |
|--------------|------------------|-----------|
| **basedpyright 24 warnings EXIT1** (타입 완전 통과 아님) | Grok 리스트가 **품질 게이트 결손**을 누락. “개발”이든 “자체검증”이든 명시 필요. | `CLAUDE-NIGHT-REVIEW-9d2041f.md:9,20`; brief 가설 10 |
| **CURSOR-HANDOFF §10 (1–4)** OpenCode descriptor 고정, RSS≠스냅샷 한도, inbox stat→unlink, source-id/cursor 마이그레이션 | Grok P1-13에 §10이 **한 줄**로만 있고 4개 결손이 분리되지 않음. §10-1~4는 **실구현 잔여**. | `CURSOR-HANDOFF-2026-09-10.md:239-243` |
| **M8/F 클라이언트 연결 준비 자료 완성** | `GROK-CLIENT-CONNECTION-READINESS` 착수만 기록, 완성 미확인. 수집기≠주입기 표는 M8 선행. | `CODEX-REMAINING-TRIAGE-2026-09-13.md:63-71` |
| **F/M6 운영 판단 자료 (잔여 2)** | `GROK-CURRENT-OPERATIONS-REVIEW` D1–D3는 Claude가 일부 수정했으나 **당일 current/프로세스/백업 hash** 등 전환 직전 항목 미완. | `GROK-COMPLETION-CONTINUATION-2026-09-13.md:33-38`; triage §4 잔여2 |
| **M3 보류 분기** (열린 연결·과거 설정/백업 rollback) | Grok “재시도 금지”로 **빼버림**. Codex: 목표 축소가 아니라 **실행 보류** — 리스트에 “blocked_deferred”로 있어야 함. | `CODEX-REMAINING-TRIAGE-2026-09-13.md:13,39,104-106` |
| **보안 경계 / symlink·FIFO / 삭제 경합 / 삭제 전 백업 수명** | 동일. 사용자는 운영전환·auth복사·삭제·push만 금지; **보안 수명 구현 자체는 금지 아님**(Codex 정정). 리스트 누락=**원 범위 축소 표현**. | triage §1:13; §6:106-108 |
| **M2/M4 격리 계보 실행 가능 준비** | “외부입력”만 강조하고 **task→record→새세션 증거 항목표** 준비가 리스트에 없음. 실행 가능한 격리 작업 은폐. | triage §5:97; `AGENT-SUPPORT-AND-ACCEPTANCE-GAPS-2026-09-10.md:22,40` |
| **JARVIS artifact `runtime` symlink 불일치** | `jarvis-artifact-64715ba`의 `runtime`→`78e7307` — 재현성 결함. 게이트 전에 정리 필요. | JARVIS 조사: artifact hygiene |
| **IMPLEMENTATION-STATUS 표 갱신** | 표는 여전히 `41f0751`/`e13cd3b`/`f7c1945` 혼재. `8d1f8cc`/`9d2041f` 미반영 — 제출물 15·16과 중복이나 **누락 시 STALE-PIN**. | `IMPLEMENTATION-STATUS.md:18`; `CLAUDE-OVERNIGHT-REPORT-2026-09-14.md:21` |

---

## 4. FALSE-COMPLETE 표

| Grok 과대평가 | 실제 | 근거 |
|---------------|------|------|
| **M9 Claude 훅 = JARVIS M9/C 닫음** | **거짓.** JARVIS `cli-gjc-commands.ts:355-357`에 model-session compaction 이벤트 없음. N1 in-turn은 **SB hook 한정**; JARVIS는 PostCompact consumer만. | `GROK-M9-SESSION-COMPACTION-CONSTRAINT-2026-09-13.md:14-16`; `CLAUDE-NIGHT-DIRECTIVE-e53dd66.md:33` |
| **M9 in-turn = N1 전체** | **거짓.** 예약→인가→전송 실패분류→재시도→재시작의 **공개 경로(N1)** 미완. RecordingModelTransport만 채우면 미완료 — `gjc.dispatch`는 기본 Recording (`cli-gjc-commands.ts:378`). | Orca-JARVIS 조사; brief P0-4 |
| **A 관리형 compile 완료** | **거짓.** `USER_EDIT_KEEP_THIS` direct `run_compile` 테스트는 통과하나 **managed staging**에서 `edit_after=false` (CODEX-6FB150B). | `tests/test_compiled_marker_recovery.py:161-171`; `CODEX-6FB150B-RECHECK` |
| **M6 writer 배제** | **거짓.** `writer_busy` 격리 스크립트만; **큐0≠배제**, 운영 서비스 cutover 없음. | `IMPLEMENTATION-STATUS.md:24`; `CURSOR-HANDOFF-2026-09-10.md:233` |
| **M12 DR 완료** | **거짓.** harness-36/b9fc3d4는 **옛 바이트** 격리 증거. 현재 핀 cold 원본·provider/control 유실·같은 런타임 RPO/RTO **미측정**. | triage §3 M12; brief P0-3 |
| **M11 MCP p50/p95/RSS** | **부분 거짓.** 7d97af7는 **f7c1945 핀**; pinned-read-during-publish **미증명**. 21.36s remember는 ops SLA 아님. | triage §2:27; §3 M11 |
| **M7 전 표면 0 누출** | **거짓.** scoped 격리 테스트만; 운영 corpus·vector/relation 일괄 인수 아님. | triage §3 M7 |
| **M13 GUI 수명** | **거짓.** Chrome CDP 격리; pending 폐기≠기억 삭제, delete-race deferred. | `IMPLEMENTATION-STATUS.md:31`; `CLAUDE-NIGHT-REVIEW-9d2041f.md:26` |
| **3게이트 EXIT0 = 현재 후보 증명** | **거짓(STALE-PIN).** gates log는 f7c1945; 후보는 8d1f8cc/2ccf0267. | brief; `CODEX-REMAINING-TRIAGE-2026-09-13.md:19` |
| **GROK-FINAL-ACCEPTANCE-PACKAGE 현재성** | **거짓.** e13cd3b/1672626·“세션 compaction 이벤트 없음” 등 **9d2041f 이전** 상태. | `GROK-FINAL-ACCEPTANCE-PACKAGE` vs `CLAUDE-OVERNIGHT-REPORT-2026-09-14.md` |

---

## 5. 살아남은 개발 리스트 (우선순위 재정렬)

| 우선 | 항목 | 완료 증거(원 플랜) | 현재 핀에서 실행할 것(한 줄) |
|------|------|-------------------|------------------------------|
| **P0-1** | **A 관리형 compile** | “무수정 정정 + 손편집 + CLI 중단 재시작, staging HEAD 덮어쓰기 금지” (`CURSOR-HANDOFF` A/M2) | managed path에서 `USER_EDIT_KEEP_THIS` 보존 수정 + `tests/test_compiled_marker_recovery.py` managed 케이스 추가 실행 |
| **P0-2** | **M12 현재 핀 DR** | “cold 원본, provider/control 유실, 같은 런타임 복원→scoped→high-water→재유입 차단→RPO/RTO” (M12) | `8d1f8cc`×`64715ba`로 harness-36 **재실행**(옛 승계 금지), anchor 없는 거부·init_vault legacy 포함 |
| **P0-3** | **M6 writer/lease** | “실제 작성자 배제, 큐0 대체 불가” (M6) | `scripts/isolated-m6-writer-cutover.py` 등을 **현재 후보 바이트**로 재실행; `deploy/check-jarvis-pending-state.py`는 drain_authorized=false 유지 |
| **P0-4** | **N1 공개 경로 (JARVIS)** | “예약→인가→전송 실패분류→재시도; Recording만으로 미완” (통합 handoff C/N1) | `gjc.dispatch`에 `CommandModelTransport` 필수화 또는 per-attempt known_not_sent/explicit negative/unknown 계약 + 통합 테스트 |
| **P0-5** | **B 철회 store** | “유실/파손/권한/symlink/동시철회, fresh stdio 2개” (B/M3) | `sb/revoked_keys.py` + MCP 격리에서 미검증 분기 테스트 추가(보류 분기는 **명시 blocked**, 재시도는 별도 승인) |
| **P0-6** | **M7 전 표면** | “제목/snippet/score/원문/벡터/관계 노출0” (M7) | CLI/web/MCP/scoped/hybrid=False 일괄 acceptance 스위트 **현재 후보**에서 실행 |
| **P0-7** | **M11 pinned-read publish** | “게시 중 pinned-read + p50/p95/RSS” (M11) | `tests/test_mcp_generation_overlap.py` 확장 또는 ops-scale corpus로 **8d1f8cc** 핀 재측정(7d97af7 승계 금지) |
| **P0-8** | **M13 GUI 수명** | “격리 GUI 전체 수명, pending≠삭제” (M13) | Chrome CDP 외 delete-race·receipt·reindex 분기 격리 테스트(보류 분기 표기) |
| **P1-1** | **§10 OpenCode (4건)** | descriptor 고정, RSS 한도, inbox unlink, cursor 마이그레이션 (`CURSOR-HANDOFF §10`) | `sb/connectors/sessions_opencode.py` + `fs_safety`에 반례 테스트→수정 |
| **P1-2** | **M8 지원표+주입** | “수집기≠주입기, 이벤트 없으면 미지원 명시” (M8) | `GROK-CLIENT-CONNECTION-READINESS` 완성 + Codex `mcp add` 등 **명시적** 경로만 문서화 |
| **P1-3** | **M9 JARVIS 한계** | “공개 이벤트 없으면 한계만; Claude 훅으로 대체 금지” (M9) | JARVIS: 이벤트 없음 **문서+테스트 고정**만(64715ba 변경 없음이면 SB 쪽만) |
| **P1-4** | **M5 사본 정책** | “클라이언트 소유 파일 금지, 빈 HOME≠미지원” (M5) | `M5-COPY-POLICY` 기준 지원 한계 표 갱신(구현은 native 경로 blocked) |
| **P2-1** | **M14** | “가치 측정 후 채택/보류, 새 그래프 없음” (M14) | 고정 질문 세트로 hybrid on/off 비용 비교 **측정만** |
| **제출** | **15–16 패키지** | A–F/M1–M14 4분류 + 현재 핀 | `GROK-FINAL-ACCEPTANCE-PACKAGE`를 `8d1f8cc`×`64715ba`×`9d2041f`로 재작성; `IMPLEMENTATION-STATUS` 표 동기화 |
| **검증(비개발)** | **게이트 재실행** | CURSOR-HANDOFF §8.B | `prepare-release`(필요 시) + 3게이트를 **8d1f8cc×64715ba**로 실행, **새 로그** 생성 — Grok 자체검증 후 Codex 최종검증 인계용 |

**재정렬 근거:** CURSOR-HANDOFF §7:159는 **M1/M2 실업무 확정 → M3–M7 → M8–M13**. Grok 1→3→2→4는 **M1/M2를 뒤로 미룸** — **우선순위 충돌**.

---

## 6. 역할 모순

| 주체 | 전제 | 모순 |
|------|------|------|
| **Grok** | 구현·자체검증·후보 고정; Codex/Claude는 **중간 패치 리뷰 없이** 최종 1회 | 리스트에 **3게이트 재실행·패키지 재작성** = 검증자/패키저 역할 혼입 |
| **Codex/Claude** | 고정 후보 전체 검증만 | **9d2041f Claude 야간**은 이미 중간 한정 인수 수행 — “중간 없음” 전제 **이미 깨짐** |
| **이번 Composer** | brief가 plan-only 적대 검증 요청 | 역할 전제상 **금지된 중간 리뷰 루프**에 해당. 판정은 인계 참고용이며 **최종 인수를 대체하지 않음** |
| **implemented_unverified** | 구현됐으나 미검증 | Grok 리스트가 **재구현(A,B,M6…)**과 **재증명(게이트)**을 구분 없이 섞음 — 가설 2 **성립** |

**가설별 판정:**

1. M9 Claude 훅 ≠ JARVIS M9/C 닫음 → **성립**
2. implemented_unverified 전부 재구현 vs 재증명 혼동 → **성립**
3. 3게이트 = 패키징, 최종검증자 역할 → **성립**
4. 보류=재시도 금지가 원목표 축소? → **부분 성립**(실행 보류≠목표 삭제; Grok 리스트는 보류를 **MISSING** 처리)
5. N1/M12/M6 반복 패치? → **부분 성립**(옛 harness 증거 STALE; 현재 핀 계약은 **여전히 없음** → 재실행 필요하나 “새 개발”과 구분)
6. M10/M2/M4 외부입력이 격리 작업 은폐? → **부분 성립**(항목표 준비 MISSING)
7. 순서 1→3→2→4 vs M1/M2 우선 → **충돌**
8. Composer 검증 = 중간 루프 → **성립**
9. PR #2 vs push 없음 → **비충돌**(기존 OPEN PR ≠ 신규 push; brief 금지는 **신규 push**)
10. basedpyright 24 warnings 누락 → **성립**

---

## 7. 하지 말 것

- **운영 current** (`41f0751` SB, `a3cbbbe` JARVIS authority) 변경·cutover·서비스 중단
- **auth/config 복사**, 실사용자 기록 삭제, **신규 push**
- **보류 분기** (보안 경계, symlink/FIFO, 삭제 경합, 삭제 전 백업 수명) **무도 재시도** — 사용자 미승인; 목표 삭제로 쓰지 말 것
- **M9 SB Claude hook 재구현** — 9d2041f 한정 인수됨
- **f7c1945 / e13cd3b / 1672626 게이트·패키지 증거**를 `8d1f8cc`×`64715ba` 증거로 **이름만 바꿔 승계**
- **Claude 훅으로 JARVIS M9 대체**
- **M14 신규 그래프/OSS**
- **중간 Codex/Claude 리뷰 루프**를 “또 하나의 최종”으로 포장
- **2n / phone-history / .bak** 삭제·이동

---

## 부록: Grok 리스트 항목별 판정 요약

| # | 판정 | 비고 |
|---|------|------|
| 1 | WRONG-BUCKET + STALE-PIN | 재실행=검증; 후보는 이미 있음 |
| 2 | KEEP | M6 운영 writer 배제 미증명 |
| 3 | KEEP | M12 현재 핀 DR 미증명 |
| 4 | KEEP | N1 JARVIS 공개 경로 미완 |
| 5 | KEEP | A managed compile 결함 |
| 6 | KEEP | B 미검증 분기 |
| 7 | KEEP | M7 일괄 인수 아님 |
| 8 | KEEP | M11 pinned-read·현재 핀 측정 |
| 9 | KEEP | M13 전체 수명 |
| 10 | KEEP + WRONG-BUCKET | 구현+문서 혼재; readiness MISSING |
| 11 | KILL(SB) / KEEP(JARVIS 한계) | SB hook 완료; JARVIS 이벤트 없음 고정 |
| 12 | WRONG-BUCKET | blocked_external |
| 13 | KEEP | §10 4건 구현 잔여 |
| 14 | KEEP | 측정만, not_implemented 유지 |
| 15–16 | KEEP | 제출물·분류표 — 개발은 아니나 필수 |
| 17 | KILL | 보존 지시 |

**최종:** Grok 리스트를 “Codex/Claude 최종 검증 전 Grok 개발”로 **무조건 채택 불가**. 위 **살아남은 개발 리스트 + 게이트 재실행(검증 분리) + 제출물 갱신**만 조건부 유효.
