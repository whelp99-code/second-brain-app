# 고정 제출 7de7c6f 독립 검토 (Claude 야간)

작성자: **Claude Fable 5.1 야간 세션**. 2026-09-13T13:10:14.628945+00:00.

**판정: 미인수(전 후보보다 개선).** 다중 단어 요약/프롬프트 주입은 이제 동작한다. 남은 차단: C1 내용 없는 프롬프트가 last_query를 덮어씀, C2 hook-replaced 순서에서 SessionStart stage가 PostCompact 잔여를 버림, C3 term 선택이 앞 8토큰이라 늦게 나오는 대상을 놓치고 noise 페이지가 예산을 채움. 일반: C4 프롬프트 원문 저장, C5 D2 분류/설치 unit 관측 행.

## 고정과 직접 실행
- 제출 `7de7c6f`, 제품 `f475adb`, 후보 `/var/tmp/sb-candidate-f475adb/releases/b277adcc789a27aa4f69b8525acca9100d61763e` wheel `35ea42744ef7b05e02ec8a8f456c3fad90d96532b5fb5c58c57e37257844de02`. 183 파일 일치. 원본 `/var/tmp/claude-night-e53dd66-GBr0la`.
- pytest hook 파일 **24 passed / 1.65s EXIT0**, Ruff EXIT0, basedpyright 0 errors / 13 warnings / EXIT1. `inturn-probe-f475adb.json` 15/17, `quality-probe-f475adb.json` 3/7.

## 통과 범위
- 7de7c6f archive: 183 files identical to wheel/installed; manifest source f475adb
- real-shaped SessionStart(compact) + PostCompact + UserPromptSubmit sequence: 15/17 inturn assertions incl. realistic multi-word summary and prompt, source!=compact {}, in-turn/PostCompact dedupe within epoch, quote tokens no crash, Hangul+ASCII prompt
- D1 fixed; D3 slots and doctor/search examples present; constraint doc restored JARVIS consumer/digest/stdout sections, matcher compact, PostCompact additionalContext not consumed
- 24 tests, Ruff clean, sb search AND unchanged

## 잔여 — 한 번의 통합 후속

### C1 (blocking) — `sb/postcompact_hook.py UserPromptSubmit _remember_last_query / _bound_query_text`
Every prompt overwrites last_query, including content-free ones. Probe: after prompts 'continue' / 'go on', stage last_query='go on' -> second SessionStart(compact) returns {} (s8); inturn-2 last_query='go'. Real sessions are full of 'ok/continue/yes' prompts, so the in-turn reselect at the next compaction degrades to nothing.

**완료조건:** Update last_query only when the prompt yields >=1 hook term (non-stop, len>=3) - no longest-token fallback for prompts; otherwise keep the prior query. Probe second_compaction_new_epoch_reinjects_last_query must pass.

### C2 (blocking) — `sb/postcompact_hook.py SessionStart branch _write_stage`
Hook-replaced order (PostCompact first, then SessionStart compact): SessionStart writes a fresh stage with its own records and delivered_in_turn=None, discarding the pending undelivered PostCompact remainder. Probe t2->t3->t4: PostCompact staged Omega+Theta, SessionStart delivered Theta, next prompt {} (Omega lost).

**완료조건:** On SessionStart(compact): deliver in-turn records; keep prior undelivered PostCompact records minus the in-turn set as the pending remainder (delivered=False) in the same stage; new epoch delivered_in_turn = in-turn set only. Probe hookreplaced_order_remainder_omega_only must pass.

### C3 (blocking) — `sb/postcompact_hook.py _hook_terms/_hook_search (_MAX_HOOK_TERMS=8, first-come order)`
Terms are the first 8 non-stop tokens in text order. quality-probe q1/q2: a realistic 60-word summary whose target OmegaInturnTarget appears after the preamble -> Omega never searched; all 8 slots filled by noise pages matching preamble words (deployment, dashboard, gateway...). late_target_selected=false, ranked_first=false. The _HOOK_STOP list is fitted to earlier probe sentences and is not a general solution.

**완료조건:** Select terms by distinctiveness, not position: gather up to 32 distinct candidate tokens (stop/short removed), query each, weight term by rarity (e.g. 1/hit-count, drop terms with 0 or too many hits), rank records by summed weight then engine rank; cap MAX_ITEMS. Keep sb search AND contract untouched. Probe: late_target_selected, late_target_ranked_first, late_target_not_only_noise.

### C4 (ordinary) — `sb/postcompact_hook.py _bound_query_text -> stage last_query`
The raw prompt (up to 4096 bytes) is persisted verbatim in state_root/.sb/session-memory/<session>.json (stage_does_not_store_raw_prompt=false). Directive: store derived bounded terms, not prompt text.

**완료조건:** Persist only the derived term tuple (bounded), never the prompt body.

### C5 (ordinary) — `GROK-CURRENT-OPERATIONS-REVIEW-2026-09-13.md D2 table and installed-file paragraph`
(a) states row says 'row present -> forbid current' which conflates terminal rows (memory_outbox settled/expired per Orca-JARVIS migrations/033 transition trigger) with unresolved ones (queued/delivering/accepted_unsettled/uncertain); other tables' value sets unknown -> must be 'unclassified => stop'. (b) installed-unit paragraph lost the exact observed rows (ConditionPathExists=/home/jm/.config/second-brain/request-executor.enabled, WorkingDirectory/ExecStart absolute current paths, Environment=SB_CONFIG=/home/jm/.config/second-brain/config.toml, drop-in 20-runtime.conf) and the observation time.

**완료조건:** Per-table state classification with unresolved/terminal/unclassified columns and {table: []} vs count>0; restore exact installed rows with time.

## 재검증
`probe-inturn.py` 17/17, `probe-quality.py` 7/7, `check-docs.py`, hook pytest/Ruff/타입. 검색 계약 불변. native/운영/보류 분기 없음.
