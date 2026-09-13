# M9 세션 compaction 계약

## 공개 훅 (Claude Code 2.1.270)

- **UserPromptSubmit**: `prompt`를 bounded lexical `last_query`로 stage에 기록. 미전달 stage가 있으면 additionalContext.
- **SessionStart `source=compact`**: `compact_summary`가 없어도 `last_query`로 재선택 후 additionalContext. last_query 없으면 `{}` exit 0.
- **SessionStart `source≠compact`**: `{}` exit 0.
- **PostCompact**: 재선택 결과를 stage. in-turn 전달분 `record_id+version`은 제외. 나머지가 없으면 delivered.
- **PreCompact**: 미지원.

native 세션에서 훅이 돈 적은 없음 (`M9_native_session`).

## 등록 예시 (운영 `~/.claude` 금지)

```json
{
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "env SB_CONFIG=/var/tmp/sb-client-readiness/config.toml /ABS/bin/sb postcompact-hook" }] }],
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "env SB_CONFIG=/var/tmp/sb-client-readiness/config.toml /ABS/bin/sb postcompact-hook" }] }],
    "PostCompact": [{ "hooks": [{ "type": "command", "command": "env SB_CONFIG=/var/tmp/sb-client-readiness/config.toml /ABS/bin/sb postcompact-hook" }] }]
  }
}
```
