# 재개 지점 — unified-db 1단계 (2026-09-17 14:40 KST)

## 지금 상태

| 항목 | 값 |
|---|---|
| 구현 커밋 | `8aec1f6` (브랜치 `claude/second-brain-app-overnight-c43f4d`) |
| 발행 브랜치 | `codex/shared-memory-completion-20260907` = `2834234` (아직 8aec1f6 미포함) |
| 검증 | 전체 회귀 1955 passed / 3 skipped, 변경 파일 ruff·basedpyright 0, 신규 테스트 4 통과 |
| 하네스 릴리스 | 1.0.2 **ABORTED** (계약이 잘못된 검증 명령으로 잠겨 있었음) |
| 하네스 수정 | `shipping-harness` `ddf32c7` — uv.lock이 있으면 `uv run --frozen`으로 검증. 단위 136 + MCP 테스트 통과, `~/.local`과 nvm 양쪽 설치 완료 |
| 미해결 | 실행 중이던 MCP 서버가 옛 코드를 들고 있어 재시작 필요 |

## 재시작 직후 할 일 (순서)

1. `mcp__shipping-harness__shipping_status`로 ABORTED 확인.
2. `shipping_start` — 목표 문구에 "읽기 전용" 같은 표현을 쓰지 말 것(의도 게이트가 분석 전용으로 고정한다). 구현 지시형으로 쓴다. 릴리스는 1.0.2.
3. 제안의 acceptance가 `uv run --frozen ruff check .` / `uv run --frozen pytest`인지 확인. 아니면 서버가 아직 옛 코드다.
4. 사용자 승인 후 `shipping_approve_scope` → `shipping_verify` → `shipping_close`.
5. 버전 표기 정리: `pyproject.toml`은 1.0.0인데 태그는 v1.0.1이다. 1.0.2 릴리스에서 맞춘다.
6. 8aec1f6을 발행 브랜치로 합치고 master·태그 푸시.

## 그다음 (운영 적용)

7. 격리 볼트에서 unified-db 수집을 실제로 돌려 결과를 사용자에게 보인다(운영 볼트 미변경).
8. 승인되면 `~/.config/second-brain/jarvis-provider.toml`에 unified-db 소스를 추가하고 relink 없이 refresh 1회로 검증. 민감도 정책은 소스별 `llm_policy`로 정한다.

## 근거 문서

- 전체 분석과 7단계 계획: `SECOND-BRAIN-LIFE-MEMORY-ANALYSIS-2026-09-17.md`
- 대상 데이터: 맥 Postgres 5433, `memory.events` 4,702건(오늘도 유입), `evidence.items` 5,090건. 잡음 `[ClaudeProbe] session` 1,548건이 단일 최다.
