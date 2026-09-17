# 재개 지점 — unified-db 1단계 (2026-09-17, 2차 갱신)

## 지금 상태

| 항목 | 값 |
|---|---|
| 작업 브랜치 | `claude/continue-session-80ebc9` = `e03c403` (발행 브랜치 `8e9491a` 위에 3커밋) |
| 구현 | `f52516e` — unified-db 커넥터가 무내용 심박 행을 건너뛴다(원본 `8aec1f6`) |
| 릴리스 준비 | `eaf2dfa` — 1.0.2 버전 표기, 저장소 전체 ruff 21건 정리 / `e03c403` — Info.plist·MCP 픽스처의 버전 결합 수정 |
| 검증 | `uv run --frozen ruff check .` 통과, `uv run --frozen pytest` 1955 passed / 3 skipped |
| 하네스 릴리스 1.0.2 | 아직 미개시 — MCP 서버 재연결 대기 |

## 하네스가 막혀 있던 진짜 원인

`ddf32c7`(uv.lock이 있으면 `uv run --frozen`)만으로는 부족했다. `project-analysis.mjs`의 `has()`가
표시용으로 **200개에서 잘린** 루트 목록을 읽는데, 이 저장소는 루트 항목이 928개라 `uv.lock`이
잘림선 뒤로 밀려 분기가 발동하지 않았다. shipping-harness `5a164d8`에서 표시용 목록과 탐지용
전체 이름 집합을 분리해 고쳤다(unit 137 + mcp 75 통과).

**남은 조건**: 실행 중인 shipping-harness MCP 서버가 옛 코드를 메모리에 들고 있다. 재연결해야 반영된다.

## 재연결 직후 할 일

1. `shipping_start` — 목표는 구현 지시형으로(「읽기 전용」 같은 표현은 의도 게이트를 분석 전용으로 고정한다), 릴리스 1.0.2.
2. 제안의 acceptance가 `uv run --frozen ruff check .` / `uv run --frozen pytest`인지 확인.
3. 사용자 승인 후 `shipping_approve_scope` → `shipping_verify` → `shipping_close`.
4. 발행 브랜치 `codex/shared-memory-completion-20260907`로 합치고 master·태그(v1.0.2) 푸시.

## 환경 주의

`uv run --frozen pytest`는 venv를 그대로 쓴다. `embeddings` 엑스트라(sqlite-vec, sentence-transformers)가
없으면 `tests/test_embeddings.py` 20건이 실패한다. 새 워크트리에서는 `uv sync --frozen --all-extras` 먼저.

## 그다음 (운영 적용)

5. 격리 볼트에서 unified-db 수집을 실제로 돌려 결과를 보인다(운영 볼트 미변경). **맥 Postgres 5433은
   SSH 터널이 있어야 닿는다 — 현재 jm-cloud에서 5433은 닫혀 있다.**
6. 승인되면 `~/.config/second-brain/jarvis-provider.toml`에 unified-db 소스를 추가하고 relink 없이 refresh 1회로 검증.

## 근거 문서

- 전체 분석과 7단계 계획: `SECOND-BRAIN-LIFE-MEMORY-ANALYSIS-2026-09-17.md`
- 대상 데이터: `memory.events` 4,702건, `evidence.items` 5,090건, 잡음 `[ClaudeProbe] session` 1,548건.
