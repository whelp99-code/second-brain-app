# 클라이언트 연결 준비 — 2026-09-14

읽기 전용. native 등록/로그인/운영 설정 변경 없음. 수집기 ≠ 주입기.

핀: SB `8d1f8cc` / 후보 `2ccf0267…` / JARVIS artifact `64715ba` / Claude Code **2.1.270** / Codex CLI 0.154.0 (13일 관측, 이번 미재실행).

## 주입 vs 수집

| 클라이언트 | 수집 adapter | 자동 주입 | 상태 |
|---|---|---|---|
| Claude Code 2.1.270 | `claude-sessions` | SessionStart compact 훅 | `verified_isolated_native (manual compact, 1 session)`. [CLAUDE-NATIVE-COMPACT-PROBE-2026-09-15.md](CLAUDE-NATIVE-COMPACT-PROBE-2026-09-15.md). auto-compaction 미관측. 운영 미전환 |
| Codex 0.154.0 | `codex-sessions` | 공개 compact 이벤트 없음. `codex mcp add`만 | 주입 미지원으로 고정 |
| OmO | `omo-sessions` | 공개 이벤트 미확인 | 미지원 |
| OpenCode | `opencode-sessions` | PATH 없음 | 미설치 |
| GJC/JARVIS | `gjc-sessions` | compaction 이벤트 없음 | `GROK-M9-JARVIS-NO-EVENT-2026-09-14.md` |

MCP `sb mcp`는 도구 호출이지 모델 문맥 자동주입이 아니다.

격리 Codex 연동 1건은 실행하지 않음. MCP 엔트리: `/var/tmp/sb-candidate-8d1f8cc/releases/2ccf0267e52da2482d215b1e47dc6bf3f0fbd0e3/bin/sb`.
