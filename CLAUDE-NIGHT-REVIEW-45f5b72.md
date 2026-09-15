# Claude 검증 리뷰 — 45f5b72 (H5/H6 readiness 종결) — 2026-09-15 18:45 KST

판정: **수락(accept)**. 3차 운영 전환 대상.

## 대상
- 제품 커밋 `45f5b72` "sweep orphan activations and supersede failed briefs" (핀 `a5c4159`), 기준 `fd66d20`(운영 current 8ea65a7 = 제품 83a7aba).
- 변경: `sb/generations.py` `sweep_orphan_activations`, `sb/generation_runtime.py` `settle_superseded_briefs` + maintain 경로 호출, `sb/store/ledger.py` `supersede_historical_brief_failures`, `DerivStatus.SUPERSEDED`(failed→superseded 전이만 허용), `sb/cli.py` maintain 이후 settle 호출, 테스트 2파일(+9).

## 검증 (격리, 이 세션)
| 항목 | 결과 |
|---|---|
| 신규 테스트 (`test_orphan_activation_sweep.py`, `test_supersede_brief_failures.py`) | 통과 |
| 전체 회귀 `uv run --frozen pytest` | 1863 passed / 50 skipped / **20 failed — 전부 `tests/test_embeddings.py`, 원인은 워크트리 venv에 `embeddings` extra(sqlite-vec) 미설치** |
| `--extra embeddings`로 `tests/test_embeddings.py` 재실행 | 30 passed / 1 skipped → 제품 회귀 0 |
| ruff (변경 7파일) | All checks passed |
| basedpyright (변경 4파일) | 0 errors (경고 13, 기존 스타일) |

## 설계 검토
- H5: `_maintain_locked` 안(배타 잠금)에서 current 제외·reader lease 핀 제외·디렉터리(또는 pointer_target) 부재 행만 `phase='proved'` + `disposal_digest=digest("generation",{reason:"orphan-missing-directory",...})`로 전이. 실재 세대는 건드리지 않음. 지시서 완료조건 충족.
- H6: `maintain` 후 별도 EFFECT mutation(`maintain:supersede-brief:*`)으로 failed brief → superseded, `derivation_event` 감사 기록, 행 삭제 없음. readiness `derivations_healthy`는 `status='failed'`만 세므로 superseded는 실패로 집계되지 않음(`sb/readiness_checks.py`). `retry_failed`는 여전히 brief 거부.
- **수락한 편차**: 지시서는 "실패 brief의 대상 일자에 이후 성공(done) 페이지가 존재할 때"였으나 구현은 "brief stage done 행이 1건 이상 존재"를 조건으로 함(brief deriv_key는 입력 해시라 일자 매핑이 원장에 없음). 운영 데이터(2026-09-05 실패 5행, 이후 daily 성공 존재)에서는 결과가 같다. 향후 일자 단위 조건이 필요하면 `finished_at`/`output_path` 비교로 강화 가능 — 별도 항목.

## 운영 적용
- 릴리스 준비: `deploy/prepare-release.py`(main checkout HEAD a5c4159) → app root releases/. 
- 3차 relink 후 `jm-second-brain-maintenance.service` 1회 실행으로 H5/H6 경로가 운영 journal/ledger에 적용됨. 결과는 `CLAUDE-CUTOVER-2026-09-15.md` 3차 항목에 기록.
