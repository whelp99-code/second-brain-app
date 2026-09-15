# 통합 후속 지시 — e53dd66 이후 (D1–D3 문서 + N1 in-turn 구현)

작성자: **Claude Fable 5.1 야간 세션** (사용자 지시로 기존 Codex 기획·설계·검증 역할을 인계. 지정 검토 터미널 `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`는 exited 상태로 확인). 구현 역할은 기존 Grok/OmO `term_dc97574f3e548cff6e25679d713ed8c2` 그대로다. 이 세션이 이후 고정 후보를 독립 검증한다.

기준: `CODEX-NIGHT-REVIEW-e53dd66.md/.json`(D1–D3), `GROK-COMPLETION-CONTINUATION-2026-09-13.md` §2 완료조건 1–5, `CODEX-REMAINING-TRIAGE-2026-09-13.md` 잔여 3. 원 A–F/M1–M14 축소 없음. 보류 분기(보안 경계/삭제 경합/복원 수명) 재시도·이전 없음. 운영 전환·auth/config 복사·실사용자 삭제·push 없음. 제품 수정은 Grok만 수행한다.

## A. D1–D3 문서 정합화 (e53dd66 검토 그대로)

`GROK-CURRENT-OPERATIONS-REVIEW-2026-09-13.md`만 고친다. 제품/테스트 재수정·동일 회귀 반복 없음.

- **D1** (:40, :23): 리포 `systemd/user/jm-second-brain-requests.service:3,7–8`에는 SB_CONFIG Environment 행이 **없다**. 그 행은 `deploy/systemd/second-brain.service:9`에만 있다. requests.service 리포 칸에서 SB_CONFIG 문구를 빼고 `sb/config.py:184–192`의 SB_CONFIG env → user config → app fallback 순서를 적는다. 제안 설정은 proposed로만 표기. 설치 unit 칸에는 읽은 정확한 경로(`~/.config/systemd/user/jm-second-brain-requests.path`/`.service`, drop-in `.service.d/20-runtime.conf` 존재)와 관측 시각, 관측 행(ConditionPathExists=…/request-executor.enabled, DirectoryNotEmpty, WorkingDirectory=…/app/current, Environment=SB_CONFIG=/home/jm/.config/second-brain/config.toml, ExecStart=…/app/current/bin/sb apply-requests --once)을 적고 활성 상태는 미관측으로 둔다. shell 변수 예시(:23)의 `%h`는 `/home/jm/.config/second-brain/config.toml` 절대 경로로 바꾼다.
- **D2** (:64): `deploy/check-jarvis-pending-state.py:46–53`의 `states`는 고정 테이블 키 객체라 결과가 비어도 객체는 비지 않는다. table/state/count별 미해결 판정 표(예: memory_outbox state≠terminal count>0 → 미해결, 분류 근거 없는 state → 미확정=정지 유지)로 바꾸고, `{table: []}`와 잔여 count를 구분한다. `counts.active_cursor_rows≠0`, `leases.gjc_runtime_leases|microloop_leases.unexpired|invalid>0`, 누락/미관측 모두 중단 조건. EXIT0/빈 결과·`drain_authorized:false`는 허가가 아님을 유지. 임의 drain/만료 처리/구버전 복귀 의뢰 없음.
- **D3** (:85–88): 슬롯 `RESTORED_ROOT`, `VERIFY_CONFIG`(격리 config 절대경로), `VERIFY_STATE_ROOT`, `VERIFY_REQUEST_ROOT`, `VERIFY_QUERY`를 분리하고 vault_root→RESTORED_ROOT, state_root/request_root→독립 슬롯 표를 적는다. **실행하지 않을** 예시로 `SB_CONFIG="$VERIFY_CONFIG" "$SB_CANDIDATE/bin/sb" doctor`, `SB_CONFIG="$VERIFY_CONFIG" "$SB_CANDIDATE/bin/sb" search "$VERIFY_QUERY"` (`sb/cli.py:98` query 필수)를 연결한다. 검증 대상이 운영 root가 아닌지 먼저 확인할 조건, 슬롯 미확정/검증 실패/불일치 시 writer 정지·current 연결·기동 금지, 이후 기동에 합의돼야 할 unit/config/candidate를 명시. 슬롯 준비≠승인≠복원 성공.

## B. N1 in-turn 잔여의 실제 공개 연결 — 구현 대상

**근거 (직접 읽음, `/var/tmp/claude-night-e53dd66-GBr0la/claude-2.1.270-hook-contract.json`):** 설치 Claude Code는 현재 **2.1.270** (`claude --version`; readiness 문서의 2.1.261은 이전 관측). 공개 문서 https://code.claude.com/docs/en/hooks 의 SessionStart matcher는 `startup|resume|clear|compact|fork`이며 SessionStart의 `hookSpecificOutput.additionalContext`가 문서화돼 있다. 바이너리 확인:

1. 모든 compaction 경로(일반 `compact_full`, reactive, hook-replaced)에서 compaction 뒤 **SessionStart hook이 `source:"compact"`로 실행**되고, 그 additionalContext는 `hook_additional_context` attachment로 `hookResults`에 들어가 **post-compaction 메시지 집합(boundary+summary+attachments+hookResults)에 포함**된다 → 같은 turn의 다음 모델 요청이 본다. 이것이 N1의 실제 in-turn 연결점이다.
2. **PostCompact** hook 입력에는 `compact_summary`가 있으나 runner(`fje`)는 `userDisplayMessage`만 사용한다. PostCompact의 additionalContext는 이 바이너리에서 소비되지 않는다(문서와 다름). 현재 제품의 "PostCompact는 stage만" 판단은 유지.
3. 순서: 일반/reactive 경로는 **SessionStart(compact) → PostCompact**, hook-replaced 경로는 PostCompact(summary 빈값) → SessionStart(compact). 따라서 SessionStart(compact) 시점에 그 compaction의 summary는 아직 없다고 가정해야 한다.
4. SessionStart 입력 스키마: `source`, `agent_type`, `model`, `session_title` 등. summary 필드 없음. UserPromptSubmit 입력에는 `prompt`가 있다.

**구현 (좁게, 기존 `sb/postcompact_hook.py` + `sb/cli.py postcompact-hook` 계층 안에서):**

1. `parse_postcompact_event`가 `hook_event_name=="SessionStart"`이고 `source`(또는 `matcher`/`how`) `=="compact"`인 이벤트를 받는다. 다른 source(startup/resume/clear/fork)는 `{}` 출력·EXIT0(문맥 주입 없음). PreCompact 등은 기존대로 HOOK_EVENT_UNSUPPORTED.
2. **query 출처**: UserPromptSubmit 처리 시 그 세션의 최신 `prompt`에서 `select_search_query`로 만든 **lexical query만** stage 파일(`state_root/.sb/session-memory/<session>.json`)에 `last_query`로 저장한다(프롬프트 원문 저장 아님, 기존 예산 한도 준수). SessionStart(compact)는 `last_query`로 기존 재선택 경로(`index.search`→`_matching_records`→`_serialize`)를 호출하고 `hookSpecificOutput={"hookEventName":"SessionStart","additionalContext":<기존 _context_text 형식>}`을 출력한다. `last_query`가 없으면 `{}` EXIT0(no_data, 성공으로 표시하지 않음).
3. **중복 주입 방지**: SessionStart(compact)가 전달한 record_id+version 집합을 stage에 `delivered_in_turn`으로 기록(stdout flush 성공 후 `confirm_delivery`와 같은 방식). 이어지는 같은 세션의 PostCompact stage는 summary 재선택 결과에서 이미 in-turn 전달된 동일 record_id+version을 제외하고 남은 것만 다음 UserPromptSubmit에 주입한다. 남은 것이 없으면 stage는 delivered로 둔다. 기존 event_digest 중복 규칙(같은 prompt_id/compaction_id 재전달=중복)은 유지.
4. 출력 실패 계약 유지: BrokenPipe → EXIT1, delivered 미확정, 재시도 시 다시 출력. hook ACK 없음 → exactly-once 주장 안 함.
5. 문서: `GROK-M9-SESSION-COMPACTION-CONSTRAINT-2026-09-13.md`를 갱신해 (a) 2.1.270 기준 SessionStart(compact) in-turn 경로 지원, (b) PostCompact additionalContext 미소비 사실, (c) hook 등록 예시(settings `hooks.SessionStart[matcher="compact"]`, `PostCompact`, `UserPromptSubmit` 세 항목 모두 `<candidate>/bin/sb postcompact-hook`, SB_CONFIG env 슬롯), (d) 남는 한계: query가 직전 prompt 기반이라 summary 기반 재선택은 다음 prompt까지 지연됨, native 로그인 세션 미실행. `GROK-CLIENT-CONNECTION-READINESS-2026-09-13.json`의 `auto_compaction_next_model_request`를 "sessionstart_compact_additional_context_2.1.270_isolated_verified"(실제 검증 후)로, `not_complete`의 `M9_in_turn_model_request_after_autocompact`는 격리 검증 범위에 맞게 갱신(native는 미완 유지).
6. 검증: `tests/test_postcompact_hook.py`에 정상 경로(prompt→compact SessionStart 주입→PostCompact 제외→다음 prompt 잔여만), source≠compact `{}`, last_query 없음 `{}`, in-turn 전달분 PostCompact 제외, 예산 한도, BrokenPipe 재시도. 변경 파일 Ruff·basedpyright, 관련 테스트만 실행(전체 회귀 반복 금지). 합성 이벤트/격리 fixture만. 실제 로그인 native 세션 실행·개인 세션 본문 읽기 없음.

JARVIS 변경 없음(64715ba 유지). 이 구현은 Claude Code 클라이언트의 SB hook 연결이며 JARVIS gjc.dispatch/CommandModelTransport 경로와 별개다.

## C. 제출

A와 B를 마친 뒤 변경만 선별 커밋(문서 커밋과 제품 커밋 분리 가능). 새 SB 고정 후보를 이전 방식대로 `/var/tmp/sb-candidate-<short>/releases/<release_id>`에 준비하고 `GROK-INTEGRATED-CANDIDATE-HANDOFF-2026-09-13.md`에 product/test/docs 핀, wheel SHA256, 후보 경로, 실행한 검사 수치(직접 실행)를 적는다. 완료 후 goal을 완료로 표시하고 대기한다. 이 세션이 격리 harness로 독립 검증하고 `CLAUDE-NIGHT-REVIEW-<short>.md/.json`을 남긴다.

추가 사용자/검토자 답변 대기 없이 A→B→C를 이어서 완료한다. 내부 goal JSON 직접 수정·옛 W4 blocked 복귀 금지.
