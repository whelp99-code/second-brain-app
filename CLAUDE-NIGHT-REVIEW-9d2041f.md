# 고정 제출 9d2041f 독립 검토 (Claude 야간) — 한정 인수, 차단 잔여 없음

작성자: **Claude Fable 5.1 야간 세션**. 2026-09-13T14:05:23.163064+00:00.

**판정: 한정 인수.** 범위는 Claude Code 2.1.270 공개 hook을 통한 M9 정상 세션 compaction in-turn 연결(격리 합성 검증)과 D1–D3 운영 문서. 차단 잔여 없음. native 로그인 세션 실행·운영 전환·보류 분기·원 A–F/M1–M14 전체 인수는 미완료로 유지.

## 고정과 직접 실행
- 제출 `9d2041f`, 제품 `8d1f8cc`, 후보 `/var/tmp/sb-candidate-8d1f8cc/releases/2ccf0267e52da2482d215b1e47dc6bf3f0fbd0e3` wheel `60d66ad6c3d488af843e7132eea2d7104528fb9b0c06ce732d110a2f4ca189f1`. source/wheel/installed 183 파일 일치. 원본 `/var/tmp/claude-night-e53dd66-GBr0la`.
- pytest hook 파일 **30 passed / 2.19s EXIT0**, Ruff EXIT0, basedpyright 0 errors / 24 warnings / EXIT1. `inturn-probe-8d1f8cc.json` **17/17**, `quality-probe-8d1f8cc.json` **7/7**, `hangul-probe-8d1f8cc.json` **3/3**, `check-docs` **10/10**. 전체 회귀(고정 archive) **1904 passed / 3 skipped / 640.09s / EXIT0**.

## 통과 범위
- 9d2041f archive: 183 files identical to wheel/installed; manifest source 8d1f8cc
- probe-inturn 17/17, probe-quality 7/7 (late target now ranked first), probe-hangul 3/3 on the frozen candidate CLI
- check-docs 10/10; handoff pins 8d1f8cc / wheel 60d66ad6…; readiness JSON keeps M9_native_session
- 30 hook tests, Ruff clean, sb search AND contract unchanged, JARVIS 64715ba unchanged

## 비고(비차단)
- N-a: Short-token (<6 chars) word-boundary filter is applied to hit.snippet, not the whole page text; a short term present elsewhere on the page but not in the snippet is dropped (conservative, fewer hits).
- N-b: Short Hangul tokens with attached particles (e.g. 배포를) no longer match the bare term 배포 under the word-boundary rule; the probe passed because a longer token (게이트웨이) carried the match. Real Korean quality remains the external M10 gold-set item.
- N-c: basedpyright 24 warnings / 0 errors on the changed files; not a gate.

## 미완료(외부 조건·보류)
- M9_native_session (no logged-in native run)
- ops_cutover
- M5
- M13_deferred
- held security/delete-race branches (not retried)
- A-F/M1-M14 full acceptance
