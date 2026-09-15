# 운영 준비(readiness) 잔여 2건 지시 — 2026-09-15 (H5/H6)

작성: Claude(검증 역할). 구현: Grok. 사용자 전권 위임. 운영 데이터 직접 수정 금지(제품 코드로만 해결). push 없음. 기준 핀: SB HEAD fd66d20(제품 83a7aba), 운영 current 8ea65a7. 완료 후 격리 후보 → 이 세션 검증 → 3차 운영 전환.

운영 `sb status`/web 콘솔 readiness가 `GENERATION_CLEANUP_STALLED`, `DERIVATIONS_FAILED`로 "운영 준비 미완료"다. 두 원인 모두 제품이 **설계상 처리 경로가 없는** 잔여이며, 이번에 정상 경로를 설계·구현한다.

## H5. activated 고아 activation 행 sweep (GENERATION_CLEANUP_STALLED)
- 사실: `~/.local/state/second-brain/generation-journal.db` `activations`에 phase='activated' 3행(2026-09-04/07/10, generation_id …b974e542/…84f964df/…abed9a62)이 남아 있고, 해당 세대 디렉터리는 존재하지 않으며 current가 아니다. `ACTIVATED-ORPHAN-ROWS-2026-09-10.md`가 "고아 행 sweep은 별도 설계 필요, journal 수동 수정 금지"로 남겼다. `sb/readiness_checks.py:generation_checks`는 phase<>'proved'이고 updated_at이 정책 창 밖이면 정지로 판정한다.
- 완료조건: `maintain`(또는 `doctor --…`가 아닌 정상 maintenance 경로)에서 **current가 아니고 pointer_target 디렉터리가 존재하지 않으며 reader pin이 없는 activated 행**을 append-only 감사와 함께 종결 phase로 전이한다(예: phase='proved' + disposal_digest에 `orphan-missing-directory` 사유 canonical digest, 또는 별도 terminal phase). 현재 parent와 실재 디렉터리가 있는 행은 절대 건드리지 않는다. 기존 `tests/test_activated_orphan_rows.py`의 의미(remember가 임의로 proved로 만들지 않음) 유지 + 새 테스트(3행 fixture sweep → readiness generation_cleanup true, 실재 세대는 불변). 운영 적용은 3차 전환 후 `jm-second-brain-maintenance.service` 정상 실행으로만.

## H6. 역사적 brief 실패 행의 정상 종결 (DERIVATIONS_FAILED)
- 사실: `derivation` 테이블 brief stage failed 5행(2026-09-05 10:26–14:36 UTC, `unresolved [^uncited]`, attempts 1, `BRIEF_REPLAY_INPUTS_UNAVAILABLE` 보류). 같은 날 `daily/2026-09-05.md`는 이후 실행으로 존재. `sb/ops.py:retry_failed`는 brief 재시도를 설계상 거부하며, `readiness_checks` `derivations_healthy`는 failures==0을 요구해 영구 미완료가 된다.
- 완료조건: 다음 규칙으로 **정상 종결 경로**를 추가한다: 실패 brief 행의 대상 일자 daily 페이지가 이후 성공 derivation(done)으로 존재하고 attempts가 소진/보류 상태이면, 해당 실패 행을 `superseded`(또는 동등 terminal status)로 전이하고 감사 이벤트(`derivation_event`)를 남긴다. 실패 이력은 삭제하지 않는다(status만 terminal). readiness는 superseded를 실패로 세지 않는다. 대상 일자에 성공 페이지가 없으면 그대로 failed 유지. CLI 노출은 `sb retry --stage brief`가 아니라 `maintain` 또는 새 `sb doctor --settle-superseded`처럼 명시적 경로 하나. 테스트: 성공 페이지 있음/없음 두 분기, web 콘솔 "처리 실패" 집계 반영.

## 공통
- 변경 파일 Ruff 0, basedpyright 0 errors, 관련 테스트 + 마지막 전체 회귀 1회 수치. `prepare-release.py /var/tmp/sb-candidate-<short>`로 후보, 인계서에 핀 기록. 추가 답변 대기 없음.
