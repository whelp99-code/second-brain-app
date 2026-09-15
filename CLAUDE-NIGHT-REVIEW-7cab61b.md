# Claude 검증 리뷰 — 7cab61b (H7 superseded brief 규칙 수정) — 2026-09-15 20:10 KST

판정: **수락(accept)**. 4차 운영 전환 대상.

- 변경: H6 supersede 조건을 "해당 실패행 finished_at 이후에 완료(done)된 brief가 있고, 오류가 `LLM unavailable`류가 아닐 때"로 제한. `_brief_stage`/`_reopen_failed`가 superseded 키 재요청 시 pending으로 재개(전이표에 FAILED→PENDING, SUPERSEDED→PENDING 추가, `requeue_failed`가 전이 검증). 테스트 +3.
- 검증: 전체 회귀 `uv run --frozen --extra embeddings pytest -q` **1933 passed / 3 skipped**(EXIT0). ruff 통과, basedpyright 0 errors(경고 7).
- 45f5b72 리뷰에서 "수락한 편차"로 적었던 전역 조건이 운영에서 실제 결함으로 드러났다(오늘 15:00 Codex 실패행 superseded → brief 재실행 불가, run failed). 이번 수정으로 지시서 원문 규칙과 일치.
- 릴리스: app root releases/13688d66… (source 7cab61b).
