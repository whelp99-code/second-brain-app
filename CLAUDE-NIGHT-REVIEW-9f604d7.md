# 고정 제출 9f604d7 독립 검토 (Claude 야간)

작성자: **Claude Fable 5.1 야간 세션**. 2026-09-13T13:31:53.216639+00:00.

**판정: 미인수(차단 잔여 1건).** in-turn/다음 prompt 수명, epoch 중복 방지, PostCompact 잔여 유지, last_query 가드, D1–D3 문서는 모두 통과. 남은 것은 후보 토큰 선택이 여전히 **위치 기준(앞 32개 distinct 토큰)**이라 요약 뒷부분의 대상이 검색조차 되지 않는 점이다.

## 고정과 직접 실행
- 제출 `9f604d7`, 제품 `bad60a6`, 후보 `/var/tmp/sb-candidate-bad60a6/releases/18725677f61d5f4f3a1fe4e2ad2d8829927aaf32` wheel `6089244996f56a43e72a370b1a8843820c3f89677e7839ba588fbcc091787eb1`. 183 파일 일치. 원본 `/var/tmp/claude-night-e53dd66-GBr0la`.
- pytest hook 파일 **28 passed / 2.00s EXIT0**, Ruff EXIT0, basedpyright 0 errors / 21 warnings / EXIT1. `inturn-probe-bad60a6.json` **17/17**, `quality-probe-bad60a6.json` 4/7, `check-docs` 10/10.

## 통과 범위
- 9f604d7 archive: 183 files identical to wheel/installed; manifest source bad60a6
- probe-inturn 17/17: documented SessionStart(compact) input, in-turn injection, epoch reset at second compaction, hook-replaced order keeps PostCompact remainder, content-free prompts do not clobber last_query, realistic multi-word summary/prompt, budgets, all exit 0
- quality: no crash on quote tokens, Hangul+ASCII prompt selects, stage stores derived terms not the prompt
- check-docs 10/10 (D1-D3), constraint doc, readiness JSON keeps M9_native_session
- 28 hook tests, Ruff clean, sb search AND contract unchanged

## 잔여

### C3b (blocking) — `sb/postcompact_hook.py _candidate_tokens (_MAX_CANDIDATE_TOKENS=32, text order)`
Direct check on the frozen archive: _candidate_tokens(late summary) returns the first 32 distinct tokens and OmegaInturnTarget (33rd) is absent, so _weighted_terms never queries it; quality-probe q2 injects only noise pages (late_target_selected=false, ranked_first=false, not_only_noise=false). Real compaction summaries are hundreds of words, so anything past the preamble is invisible.

**완료조건:** Choose the <=32 tokens to search by a position-independent prior over ALL distinct tokens of the bounded text (e.g. term frequency within the text desc, then token length desc / mixed-case-digit-Hangul identifiers first), then apply the existing 1/hit-count weighting. Do not raise the cap by position. Probe: late_target_selected, late_target_ranked_first, late_target_not_only_noise must pass; add a unit test whose target appears after >=40 distinct tokens.

### T1 (ordinary) — `tests/test_postcompact_hook.py`
basedpyright warnings rose from 13 to 21 on the changed files (0 errors).

**완료조건:** Reduce or annotate; not a gate.

## 재검증
`probe-quality.py` 7/7과 `probe-inturn.py` 17/17, `check-docs.py`, hook pytest/Ruff/타입. 검색 계약 불변. native/운영/보류 분기 없음.
