# M9 모델 세션 compaction 이벤트 — 소스 제약 (2026-09-13)

원 M9: 실제 세션 문맥 compaction 이벤트 → 기억 재선택 → 선택 세션 transport.

## 공개 이벤트

`Orca-JARVIS/src/cli-gjc-commands.ts` 356–357행 (git 추적 소스):

> Selected-session transport for explicit `gjc.dispatch` after `configureGjc`.
> JARVIS has no model-session context-compaction event; deletion/correction compaction is not this trigger.

삭제/정정 lane compaction (`memory-deletion-saga.ts`, `memory-content-purge.ts`)은 이 트리거가 아니다.

SB `git ls-files` + `rg compaction`에서 모델 세션 compaction 공개 콜백/이벤트 구독은 없다. RecordingModelTransport / 미호출 helper로 완료 처리하지 않는다.

## 있는 공개 경로 (compaction이 아님)

명시적 `gjc.dispatch` + `assemble_context` → `assembleDispatchContext` → `reader.read` → `AssembledModelSession` / `sendAssembledModelRequest`. 이는 기존 선택된 세션 transport이며 **compaction 이벤트 연결이 아니다**.

## 상태

M9 compaction 이벤트 연결: **미구현**. 차단은 인증 복사가 아니라 **제품에 해당 공개 이벤트가 없음**. 이번 변경으로 가짜 이벤트를 만들지 않았다.

관련 정상/실패/재시도/본문·버전·예산은 기존 `gjc.dispatch` 경로 증거(713e453 등)를 compaction 완료로 재사용하지 않는다.
