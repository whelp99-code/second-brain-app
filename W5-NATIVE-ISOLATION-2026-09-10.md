# W5 격리 native 경계 — 인증 복사 없음

운영 `~/.claude` / `~/.codex` / `CODEX_HOME`을 덮어쓰지 않았고, 운영 인증 파일을 복사하지 않았다. `HOME`은 실험 프로세스에만 `/var/tmp/w5-native-lab/...`로 줬다.

| 제품 | 버전 | 명령 | 격리 저장 | 운영 홈 항목 |
|---|---|---|---|---|
| Claude Code | 2.1.261 | `claude mcp list` | `CLAUDE_CONFIG_DIR` 아래 새 `.claude.json`(로컬 생성, MCP 서버 0) | 최상위 이름 불변 |
| Codex CLI | 0.154.0 | `codex --version` | 격리 `~/.codex/tmp`에 sandbox 바이너리 | 최상위 이름 불변 |

기억 저장→회수→정정→provider 삭제→재개는 **하지 않았다.** 인증 없는 격리 프로필은 MCP/세션 기억을 만들지 못한다. 이 조합은 M5 삭제 수명을 보장하지 않으므로 **미지원(인증·MCP 없는 빈 프로필)**. 합성 `session.jsonl` 테스트를 대신하지 않는다.

Cursor `1` 경로의 `--version`은 이 실행에 넣지 않았다. OpenCode 바이너리 없음.
