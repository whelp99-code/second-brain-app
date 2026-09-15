# 지시 H7 — superseded brief 규칙 수정 (운영 결함, 2026-09-15 19:58 KST)

작성: Claude(검증). 구현: Grok. 사용자 전권 위임. push 없음. 기준: HEAD 4fc40c1(제품 45f5b72), 운영 current 62ffbc9d.

## 운영에서 관측된 결함
- 15:00 refresh에서 오늘(2026-09-15) brief 행 `4a635cb0…`이 `LLM unavailable … Codex` 로 failed(일시 장애, 재실행 가능).
- 18:41 maintenance의 H6 `supersede_historical_brief_failures`가 "brief done 행이 하나라도 있으면" 조건으로 이 행까지 superseded로 전이(감사 event 5288).
- 19:52 refresh(LLM을 Grok으로 교체 후): ingest ok, compile ok(2행 done), **brief failed(20ms, error 공백)**. 원인: `sb/pipeline.py:_brief_stage`가 같은 키를 다시 요청 → `existing.status == 'superseded'` 는 DONE/FAILED 어느 분기도 아니어서 `mark_running` → `InvalidDerivationTransition`(superseded→running 금지) → `StageReport(errors=1)` 무메시지 → run failed, readiness `LAST_RUN_UNSUCCESSFUL` 지속. 오늘 brief 페이지를 만들 수 없는 상태.

## 완료조건
1. H6 조건 강화: failed brief 행은 **그 행의 finished_at 이후에 finished_at을 가진 done brief 행이 존재할 때만** superseded(지시서 원문 "이후 성공"). 같은 날 이전 성공(11:28)은 15:00 실패를 대체하지 못한다. 가능하면 error가 `LLM unavailable`류(일시 장애)인 행은 제외한다.
2. `_brief_stage`: existing.status가 SUPERSEDED면 오류 없이 정상 스킵(`StageReport((),0,0,0,False)`) 또는 명시 재개(SUPERSEDED→PENDING 전이 추가 + `_reopen`) 중 하나를 택하고 이유를 커밋 메시지에 남긴다. 어느 쪽이든 run은 실패하지 않아야 한다.
3. **운영 데이터 복구 경로**: 이미 superseded된 오늘 행 `4a635cb0…`은 제품 경로로만 복구한다 — 2의 "재개" 선택 시 다음 refresh가 자동 복구; "스킵" 선택 시 `sb retry --stage brief --key <key>` 같은 명시 경로가 superseded→pending을 허용해야 한다(역사적 09-05 행은 그대로 superseded 유지).
4. 테스트: (a) 이전 done만 있는 failed brief는 superseded되지 않음, (b) 이후 done이 있으면 superseded, (c) superseded 키 재요청 시 run 성공, (d) 복구 경로. 전체 회귀는 `uv run --frozen --extra embeddings pytest -q`로 1회(embeddings extra 없이 돌리면 test_embeddings 20건이 환경 실패로 나온다).
5. Ruff 0 / basedpyright 0 errors, `prepare-release.py /var/tmp/sb-candidate-<short>` 격리 후보, 인계서 핀. 추가 답변 대기 없음.
