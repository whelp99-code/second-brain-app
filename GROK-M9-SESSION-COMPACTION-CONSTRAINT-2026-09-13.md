# M9 세션 compaction 계약

## 공개 훅 (Claude Code 2.1.270)

- **UserPromptSubmit**: `prompt`를 bounded `last_query`로 stage. 미전달 stage가 있으면 additionalContext.
- **SessionStart `source=compact` / matcher compact**: `compact_summary`가 없어도 `last_query`로 재선택. 없으면 `{}` exit 0. **새 epoch**: 이번 전달분만 `delivered_in_turn`. 이전 compaction 누적 제외 없음.
- **SessionStart `source≠compact`**: `{}` exit 0.
- **PostCompact**: additionalContext를 **소비하지 않음** (stage만). 같은 epoch의 in-turn `record_id+version`만 제외. 검색은 MCP/sb search AND 계약을 바꾸지 않고, hook 안에서 짧은/불용 토큰을 뺀 후보 term별 검색 후 일치 수·relevance로 집계.
- **질의 한계**: 프롬프트/`last_query` 기반. 요약에 고유 토큰이 없으면 0건.
- **PreCompact**: 미지원.

native 세션에서 훅이 돈 적은 없음 (`M9_native_session`).

## JARVIS 소비자

`JARVIS_MODEL_TRANSPORT_CMD` (+ JSON `JARVIS_MODEL_TRANSPORT_ARGS`)가 캡처 JSON을 stdin으로 받아 **exit 0**일 때만 accepted. `FileModelTransport`는 로그이며 accepted:false (`FILE_TRANSPORT_NOT_CONSUMER`).

## 이벤트 수명

digest = session_id + 제공된 모든 occurrence 필드(prompt_id·compaction_id·event_id·uuid) + summary. 같은 prompt_id에 compaction_id c1→c2는 새 compaction. 같은 전체 키 재전달은 중복.

## 출력 실패

UserPromptSubmit / SessionStart compact는 stdout flush 성공 후에만 delivered. BrokenPipe 후 재시도는 문맥을 다시 낸다. hook ACK 없음 → exactly-once 주장 안 함.

## 등록 예시 (운영 `~/.claude` 금지)

```json
{
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "env SB_CONFIG=/var/tmp/sb-client-readiness/config.toml /ABS/bin/sb postcompact-hook" }] }],
    "SessionStart": [{ "matcher": "compact", "hooks": [{ "type": "command", "command": "env SB_CONFIG=/var/tmp/sb-client-readiness/config.toml /ABS/bin/sb postcompact-hook" }] }],
    "PostCompact": [{ "hooks": [{ "type": "command", "command": "env SB_CONFIG=/var/tmp/sb-client-readiness/config.toml /ABS/bin/sb postcompact-hook" }] }]
  }
}
```
