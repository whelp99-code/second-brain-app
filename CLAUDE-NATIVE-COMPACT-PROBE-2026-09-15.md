# native `/compact` 실행 결과 — 2026-09-15 (M9_native_session 근거)

실행: 사용자, 로그인된 Claude Code 2.1.270, 격리 프로젝트 `/var/tmp/sb-native-probe-8d1f8cc/project`, 후보 `8d1f8cc`. 세션 `23bab67c-7a6f-4799-9bb9-92c684a78bd3`. 증거 `/var/tmp/claude-night-e53dd66-GBr0la/native-probe/` (hook-io.log, stage.json, settings.json, transcript-excerpt.json, report.json). 작성: Claude Fable 5.1, 2026-09-15T00:50:03.833109+00:00.

## 관측 순서 (모두 rc=0)
1. **UserPromptSubmit** `nativeprobetarget 배포일정 알려줘.` → `{}`, `last_query=nativeprobetarget` 저장.
2. **SessionStart source=compact** (실제 입력에 summary 없음) → `additionalContext` 출력: record `wiki/native-probe` (record_id `sbrecord:v1:2d62784c…`, version, source_ref `me-wiki:notes/native-probe.md`, 본문 “NativeProbeTarget rollout window for the gateway is Tuesday evening.”).
3. **PostCompact** trigger=manual, compact_summary 있음 → `{}` stage. stage: delivered=true, delivered_in_turn=[해당 record], remainder=[].
4. **transcript**: row 110 compact summary → row 122 `attachment.type=hook_additional_context hookName=SessionStart`에 주입 본문 존재 → row 130 사용자 “방금 배포 일정이 언제라고 했지?” → row 137 모델 답변 “**화요일 저녁** … NativeProbeTarget 게이트웨이 롤아웃 창은 화요일 저녁 … `vault/wiki/native-probe.md`”.
5. compaction 후 **UserPromptSubmit** → `{}` (in-turn 전달분 제외, 중복 주입 없음).

## 판정
- SessionStart(compact)가 PostCompact보다 먼저 실행되고, 주입 문맥이 post-compaction 메시지 집합(attachment)에 들어가 다음 모델 요청 전에 존재함을 **실제 native 세션에서 확인**. 2.1.270 바이너리 분석과 일치.
- 한계: 세션 1회, 수동 `/compact`(auto 트리거 미관측). 답변에는 compaction summary도 있었으므로 주입 attachment의 존재는 증명되나 답변 귀속을 주입만으로 단정하지 않음. 격리 vault/config만 사용, 운영 설정 불변.

`M9_native_session`: `blocked_external` → **verified_isolated_native (manual compact, 1 session)**. 원 A–F/M1–M14 전체 인수와는 별개.
