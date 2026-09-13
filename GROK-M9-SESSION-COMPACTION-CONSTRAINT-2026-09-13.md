# M9 세션 compaction — 클라이언트 계약 vs JARVIS (2026-09-13)

원 M9: compaction 완료 → 기억 재선택 → 같은 세션 다음 요청/transport.

## 조사한 공개 계약

| 제품 | 버전 | 위치 | 결과 |
|---|---|---|---|
| Claude Code | 2.1.261 (`/home/jm/.local/share/claude/versions/2.1.261`) | 바이너리 문서: `PreCompact`/`PostCompact` matcher `manual`/`auto`; stdin JSON (`session_id`, compaction details); stdout `hookSpecificOutput.additionalContext` | **공개 이벤트 있음** |
| JARVIS | src `cli-gjc-commands.ts:356` (1672626) | “no model-session context-compaction event”; 삭제/정정 compaction은 트리거 아님 | 이벤트 없음. `gjc.dispatch`는 명시적 선택 세션 |
| Codex CLI | 0.154.0 `@openai/codex` | `plugin`/`app-server` --help. 패키지 `rg` compact/PreCompact **0건** | 공개 compaction 훅 미확인. `mcp add`는 TOML 등록이지 compaction 아님 |
| OmO | 5.0.0-0.beta.53 | `sessions_omo.py` `_DENIED`에 `"compaction"` — **수집 skip**이지 주입 이벤트 아님 | 주입 계약 없음 |
| Orca IDE | 1.4.197 `orca-ide status --json` | native 세션/모델 미호출 | compaction 콜백 미확인 |

허구 JARVIS 이벤트/Recording 버퍼로 완료하지 않음.

## 구현 (Claude PostCompact만)

실행 진입점: `sb postcompact-hook` (stdin=Claude 훅 JSON, stdout=Claude `hookSpecificOutput`).

경로: `parse_postcompact_event` → `SearchIndex.search` (기존 재선택) → `additionalContext`에 session_id·page_id·source_ref·version·excerpt·예산. 같은 Claude 세션의 다음 모델 요청에 주입되는 공개 transport가 `additionalContext`다. JARVIS `AssembledModelSession.send` / `RecordingModelTransport`를 이 훅이 호출하지 않는다.

검증: `uv run pytest -q tests/test_postcompact_hook.py` → 4 passed (합성 이벤트). 로그인된 native Claude 세션에서 훅이 돈 적은 **없음**.

실패: `PreCompact`/비JSON → exit 2; `SEARCH_QUERY_*` → exit 1, `additionalContext` 없음.

미등록: `~/.claude` / 운영 settings에 훅을 쓰지 않음. 예시만:

```json
{
  "hooks": {
    "PostCompact": [
      {
        "matcher": "auto",
        "hooks": [{
          "type": "command",
          "command": "/var/tmp/sb-candidate-<NEW>/releases/<id>/bin/sb postcompact-hook"
        }]
      }
    ]
  }
}
```

`SB_CONFIG`로 격리 vault를 가리킨다. 운영 config 금지.

## 상태

- Claude 공개 PostCompact → SB 재선택 → additionalContext: **구현, 합성 검증, native 미실행**
- JARVIS model-session compaction 이벤트: **없음 (제품 제약)**
- 전체 M9/native 인수: **아님**
