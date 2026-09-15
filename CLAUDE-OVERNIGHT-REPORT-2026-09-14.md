# 야간 보고 — 2026-09-13 밤 → 2026-09-14 아침 (Claude Fable 5.1)

작성 시각: 2026-09-13 23:1x KST 초판 (08:00 KST 이후 갱신 예정). 작성자: Claude 야간 세션(사용자 지시로 Codex 기획·설계·검증 역할 인계). 구현: 기존 Grok/OmO `term_dc97574f3e548cff6e25679d713ed8c2`.

## 한 줄 결론
M9 정상 세션 compaction의 **in-turn 연결**을 Claude Code 2.1.270 공개 hook(SessionStart source=compact)으로 구현·격리 검증해 한정 인수했다(제출 `9d2041f`, 제품 `8d1f8cc`). 그 과정에서 기존 hook 전체가 실세션 입력에서는 no_data였던 근본 결함(all-terms 질의)을 발견·수정했다. native 로그인 세션 실행·운영 전환·보류 분기·원 A–F/M1–M14 전체 인수는 **미완료**다.

## 시작/종료 커밋
- 시작: `e53dd66` (제품 `a41b70d`, JARVIS `64715ba`). 기존 Codex 검토 e53dd66: D1–D3 문서 잔여, N1 in-turn 한계.
- 종료(현재): `9d2041f` docs pin / 제품 `8d1f8cc`. JARVIS 변경 없음(`64715ba`). push 없음. 운영 current `41f0751` 변경 없음.
- 커밋 순서: 74c9877(docs) → cffaf9e → a18396f → 5680155 → a47f2a9 → f475adb → 7de7c6f → bad60a6 → 9f604d7 → e02bc15 → 46a3d60 → 8d1f8cc → 9d2041f.

## 독립 조사에서 확인한 사실
1. 설치 Claude Code는 **2.1.270** (readiness 문서의 2.1.261은 이전 관측). 바이너리 strings 확인: 모든 compaction 경로에서 SessionStart hook이 `source:"compact"`로 실행되고 그 `additionalContext`가 post-compaction 메시지 집합에 포함되어 같은 turn의 다음 모델 요청이 본다. PostCompact hook은 `compact_summary`를 받지만 runner는 `userDisplayMessage`만 소비(additionalContext 무시). 근거 `/var/tmp/claude-night-e53dd66-GBr0la/claude-2.1.270-hook-contract.json`.
2. 기존 `sb postcompact-hook`의 질의 선택이 all-terms(AND)라서 실제 다중 단어 요약/프롬프트에서 record 0건 → 실세션 기준 hook 경로가 항상 no_data였다(a41b70d에서 재현). 이전 검토들은 단일 단어 fixture만 사용했다.

## 구현된 것 (제품 `sb/postcompact_hook.py`, 테스트, 문서)
- SessionStart(source=compact) → 세션의 `last_query`(UserPromptSubmit prompt에서 파생한 term, 원문 저장 아님; 내용 없는 프롬프트는 덮어쓰지 않음)로 재선택 → `hookSpecificOutput.additionalContext` in-turn 주입. source≠compact는 `{}` exit 0.
- PostCompact는 stage만; 같은 epoch의 in-turn 전달분(record_id+version) 제외; hook-replaced 순서에서도 잔여 유지; SessionStart마다 새 epoch.
- 질의 선택: 텍스트 전체 distinct 토큰을 빈도/식별자 형태/길이로 순위화해 32개 선택 → term별 검색 → 1/hit 희소도 가중 → record 정렬. 6자 미만 토큰은 단어 경계 일치만 집계. `sb search`/MCP의 AND 계약은 불변.
- 문서: D1–D3(ops review), constraint 문서(2.1.270 계약, 등록 예시 matcher compact, JARVIS 소비자/digest/출력 실패), readiness JSON(`M9_native_session` 미완 유지), IMPLEMENTATION-STATUS M9 행.

## 독립 검증 (모두 격리 합성, 고정 후보 CLI 직접 실행)
- harness `/var/tmp/claude-night-e53dd66-GBr0la`: identity(archive↔wheel↔installed 183파일), run-checks(pytest/Ruff/basedpyright), probe-inturn 17 assertion, probe-quality 7, probe-hangul 3, check-docs 10. 후보별 JSON 보존.
- 최종 9d2041f/8d1f8cc: pytest hook 30 passed/2.19s, Ruff 0, basedpyright 0 errors/24 warnings(EXIT1, 완전 통과 아님), inturn 17/17, quality 7/7, hangul 3/3, docs 10/10. 전체 회귀(고정 archive, `tests` 전체): **1904 passed / 3 skipped / 640.09s / EXIT0** (`/var/tmp/claude-night-e53dd66-GBr0la/full-regression-9d2041f.log`, 직접 실행).
- 검토서: CLAUDE-NIGHT-REVIEW-{a18396f,a47f2a9,7de7c6f,9f604d7,46a3d60,9d2041f}.md/.json.

## 미완료·필요한 외부 입력 (밤에 묻지 않음)
| 항목 | 필요한 것 | 준비된 것 |
|---|---|---|
| M9 native | 실제 로그인된 Claude Code 세션에서 compaction 1회 실행 허가(사용자 직접) | **준비 완료(미실행)** `/var/tmp/sb-native-probe-8d1f8cc/README.md`: 격리 vault·config·`project/.claude/settings.json`(3 hook, matcher compact). 절차: `cd /var/tmp/sb-native-probe-8d1f8cc/project && claude` → 프롬프트 → `/compact` → 다음 답변·stage JSON 확인. hook 명령은 합성 이벤트로 smoke 확인 |
| 운영 전환(F/M6) | 서비스 중단·writer 배제·current 교체 허가, 당일 pending/lease/handles 점검 | GROK-CURRENT-OPERATIONS-REVIEW(D1–D3 정합) |
| M2/M4 실제 업무 | JARVIS task ID 또는 원문 경로·공유 대상 | 기존 계보 자료 |
| M10 한글 gold | 실제 질문 100–300·정답 근거 | 평가 도구 |
| M5/M13 보류 분기 | 재시도·이전 승인 없음(그대로 보류) | — |
| 30분 자동화 | 실행 109/110 스냅샷에 MCP HTTP 401 token_expired. 자동화 Codex의 실질 감시는 미확인. 재로그인 여부는 사용자 판단 | control JSON night_shift에 이 세션의 상태 기록 |

## 보류·원칙 유지
보안 경계/삭제 경합/복원 수명 보류 분기 재시도·이전 없음. auth/config 복사·실사용자 삭제·push·새 자동화/모델 없음. 30분 자동화 미변경.
