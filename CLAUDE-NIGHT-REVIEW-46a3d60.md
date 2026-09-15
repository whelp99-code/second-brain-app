# 고정 제출 46a3d60 독립 검토 (Claude 야간) — 한정 인수

작성자: **Claude Fable 5.1 야간 세션**. 2026-09-13T13:53:34.720728+00:00.

**판정: 한정 인수.** 범위는 Claude Code 2.1.270 공개 hook(SessionStart source=compact / PostCompact / UserPromptSubmit)을 통한 M9 정상 세션 compaction in-turn 연결의 **격리 합성 검증**과 D1–D3 운영 문서다. native 로그인 세션 실행·운영 전환·원 A–F/M1–M14 전체 인수는 미완료로 유지한다. 순위 품질 잔여 1건(Q1)은 비차단 후속으로 전달한다.

## 고정과 직접 실행
- 제출 `46a3d60`, 제품 `e02bc15`, 후보 `/var/tmp/sb-candidate-e02bc15/releases/34429e1eed029a3ac000daa561f26c2432c2d8a0` wheel `e715b968d4ca338d47d17b67151685f37f68351c808f9ca48caa51dcd3e4ae19`. source/wheel/installed 183 파일 일치. 원본 `/var/tmp/claude-night-e53dd66-GBr0la`.
- pytest hook 파일 **29 passed / 2.21s EXIT0**, Ruff EXIT0, basedpyright 0 errors / 22 warnings / EXIT1. `inturn-probe-e02bc15.json` **17/17**, `quality-probe-e02bc15.json` **6/7**, `check-docs` **10/10**.
- Claude Code 계약 근거 `/var/tmp/claude-night-e53dd66-GBr0la/claude-2.1.270-hook-contract.json`.

## 통과 범위
- 46a3d60 archive: 183 files identical to wheel/installed; manifest source e02bc15
- probe-inturn 17/17 on the frozen candidate CLI with documented input shapes: SessionStart(source=compact) in-turn injection from last_query, source!=compact {}, PostCompact staging, epoch dedupe, hook-replaced order remainder, content-free prompts do not clobber last_query, realistic multi-word summary/prompt, budgets, all exit 0
- quality 6/7: late target selected via frequency/identifier/length token ranking + 1/hit weighting; quote tokens no crash; Hangul+ASCII prompt; stage stores derived terms only
- check-docs 10/10 (D1-D3), constraint doc (2.1.270 SessionStart compact, PostCompact additionalContext not consumed, JARVIS consumer/digest/stdout sections, matcher compact), readiness JSON keeps M9_native_session
- 29 hook tests, Ruff clean, sb search AND contract unchanged

## 비차단 잔여

### Q1 (ordinary) — `sb/postcompact_hook.py _weighted_terms/_hook_search (instr substring hits)`
Short common tokens matching inside identifiers get rarity weight: in quality-probe the token 'Later' hits only wiki/theta because it is a substring of 'ThetaLaterTarget' (weight 1.0), so theta outranks omega (target is #2 of 8, still injected). Also the 32-token cap dropped 'window'/'confirmed' which would have boosted omega. late_target_ranked_first=false; all other 6 quality assertions pass.

**완료조건:** Non-blocking: e.g. require whole-word (boundary) match for short tokens (<6 chars) when computing hits, or scale weight by token length; keep sb search contract unchanged. Probe late_target_ranked_first.

### T1 (ordinary) — `tests/test_postcompact_hook.py`
basedpyright 22 warnings (0 errors).

**완료조건:** optional cleanup

## 미완료(외부 조건·보류)
- M9_native_session (no logged-in native run)
- ops_cutover
- M5
- M13_deferred
- security_delete_race_branches (held, not retried)
- A-F/M1-M14 full acceptance
