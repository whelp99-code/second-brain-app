# 고정 제출 a18396f 독립 검토 (Claude 야간)

작성자: **Claude Fable 5.1 야간 세션** (2026-09-13 사용자 지시로 Codex 검토 역할 인계; 지정 Codex 터미널 exited). 2026-09-13T12:41:55.212922+00:00.

**판정: 미인수.** A(D1–D3) 미충족, B의 in-turn 경로는 실제 SessionStart(compact) 입력 모양에서 동작하지 않음(HOOK_QUERY_MISSING exit 2), in-turn↔다음 prompt 중복 주입 방지 없음. 원 A–F/M1–M14 전체 미완료·보류 분기 미검증 유지.

## 고정과 바이트
- 제출 `a18396f`, 제품 `cffaf9e`, 문서 `74c9877`. 후보 `/var/tmp/sb-candidate-cffaf9e/releases/ba33e5e8b0d46585076352b78ac48e09902e159f` wheel `989da1a3b295635f5272eedcaa1d7ec7e58dd57bb0e18538a4bb49080f2a17d4`.
- source/wheel/installed **183 파일 일치**, manifest source_commit=cffaf9e, wheel 일치. hook sha `623753b5796c5dce…`. 원본 `/var/tmp/claude-night-e53dd66-GBr0la` (identity.json, review.tar, sb/).
- 직접 실행: pytest `tests/test_postcompact_hook.py` **17 passed / 1.40s EXIT0**, Ruff EXIT0, basedpyright 0 errors / 13 warnings / EXIT1 (완전 통과 아님). 합성 probe `inturn-probe-cffaf9e.json` (기존 a41b70d 기준선 `inturn-probe-baseline-a41b70d.json`).
- Claude Code 계약 근거: `/var/tmp/claude-night-e53dd66-GBr0la/claude-2.1.270-hook-contract.json` (2.1.270 바이너리: SessionStart source=compact가 모든 compaction 경로에서 실행되고 additionalContext가 post-compaction 메시지에 포함; PostCompact additionalContext 미소비; SessionStart 입력에 summary 없음).

## 통과 범위
- source/wheel/installed 183 files identical to a18396f archive; manifest source_commit cffaf9e; wheel sha matches
- SessionStart(compact) with synthetic summary emits hookEventName SessionStart additionalContext within budget (unit tests)
- UserPromptSubmit path, PostCompact staging, duplicate event_digest, BrokenPipe retry preserved (17 passed)
- no product change outside sb/postcompact_hook.py and its test

## 잔여 — 한 번의 통합 후속

### B1 (blocking) — `sb/postcompact_hook.py:83-90 (cffaf9e)`
SessionStart(compact) handler requires query/compact_summary in the hook input. Claude Code 2.1.270 SessionStart input schema carries source/agent_type/model/session_title only (no summary). Frozen candidate CLI with a real-shaped event {hook_event_name:SessionStart,source:compact,session_id} -> stderr HOOK_QUERY_MISSING, exit 2, no additionalContext (inturn-probe-cffaf9e.json s0,s3). Unit tests pass only because the synthetic _session() fixture adds compact_summary.

**완료조건:** Record last UserPromptSubmit prompt as bounded lexical query (last_query) in the session stage; SessionStart(compact) reselects from last_query; no last_query -> {} exit 0 (no_data). Test must use the documented input shape without summary.

### B2 (blocking) — `sb/postcompact_hook.py handle_postcompact PostCompact/UserPromptSubmit`
After an in-turn SessionStart delivery, the following PostCompact (different event_digest) writes a fresh stage and the next UserPromptSubmit re-injects the same record_id+version (probe s5 shows Omega re-injected). Directive B.3 dedupe not implemented.

**완료조건:** Track delivered_in_turn record_id+version set per session; PostCompact stage excludes them; empty remainder -> stage delivered. Keep event_digest duplicate rule. Probe: prompt_after_same_not_reinjected and prompt_after_other_only_theta must pass.

### B3 (ordinary) — `sb/postcompact_hook.py parse SessionStart`
SessionStart source!=compact raises HOOK_EVENT_UNSUPPORTED -> exit 2. With a single hook registration for SessionStart (matcher compact) this is unreachable, but a registration without matcher would surface hook errors on every startup/resume. Directive asked {} exit 0 for non-compact sources.

**완료조건:** Return {} exit 0 for startup/resume/clear/fork; keep PreCompact etc. unsupported.

### B4 (ordinary) — `GROK-M9-SESSION-COMPACTION-CONSTRAINT-2026-09-13.md; GROK-CLIENT-CONNECTION-READINESS-2026-09-13.json`
Constraint doc not updated (still says only UserPromptSubmit documented, PostCompact stage only) ; no hook registration example (SessionStart matcher compact + PostCompact + UserPromptSubmit -> <candidate>/bin/sb postcompact-hook, SB_CONFIG slot); readiness JSON dropped M9_native_session from not_complete although native was not executed; PostCompact additionalContext-ignored fact and query-source limitation not stated.

**완료조건:** Directive B.5 items (a)-(d); keep M9_native_session in not_complete; state that in-turn query is prompt-based and summary-based reselection lands at next prompt.

### A-D1 (ordinary) — `GROK-CURRENT-OPERATIONS-REVIEW-2026-09-13.md:20,40 (74c9877)`
doc line with `SB_CONFIG=%h/.config/second-brain/config.toml` still attributed to repo jm-second-brain-requests.service (systemd/user/jm-second-brain-requests.service has no Environment line: lines 1-17 read); shell var block still `SB_CONFIG=%h/...`; sb/config.py:184-192 env->user->app fallback not cited

**완료조건:** remove SB_CONFIG from repo requests.service row, cite sb/config.py:184-192 order, absolute /home/jm path in shell block

### A-D2 (ordinary) — `GROK-CURRENT-OPERATIONS-REVIEW-2026-09-13.md:34,57`
`states` 비어 있지 않음 unchanged; new text lists inspect() states keys gjc_runtime/gjc_intents/gjc_intent_leases/gjc_microloop_leases and counts.unexpired_lease_rows which do not exist. deploy/check-jarvis-pending-state.py STATES = memory_outbox(state), memory_outbox_attempts(outcome), memory_candidate_dispatch_publications(state), collaboration_bridge_outbox(state), pre_gjc_report_outbox(state), outbox(outcome); COUNTS = cursor_rows, active_cursor_rows, gjc_lease_rows, microloop_lease_rows; leases = gjc_runtime_leases, microloop_leases

**완료조건:** per table/state/count unresolved table with real keys; {table: []} vs count>0 distinction; unknown state => stop

### A-D3 (ordinary) — `GROK-CURRENT-OPERATIONS-REVIEW-2026-09-13.md restore paragraph`
no RESTORED_ROOT/VERIFY_CONFIG/VERIFY_STATE_ROOT/VERIFY_REQUEST_ROOT/VERIFY_QUERY slots; no `SB_CONFIG="$VERIFY_CONFIG" $SB_CANDIDATE/bin/sb doctor|search "$VERIFY_QUERY"` examples; restore paragraph unchanged in substance

**완료조건:** as directive A.D3

## 재검증 방법 (이 세션이 실행)
`/var/tmp/claude-night-e53dd66-GBr0la/probe-inturn.py <candidate bin/sb>`의 11개 assertion 전부 통과 + `check-docs.py <archive>` 10개 통과 + 해당 pytest/Ruff/타입. 실제 로그인 native 세션·운영 전환·auth/config 복사·실사용자 삭제·push·보류 분기 재시도 없음.
