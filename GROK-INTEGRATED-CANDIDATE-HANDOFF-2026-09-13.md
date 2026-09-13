# 통합 고정 후보 인계 — 2026-09-13

지정 검토: Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. 제품 수정은 이 Grok 커밋. 운영전환/push/인증복사/실사용자삭제 없음. 보류 보안/삭제 분기 재실행 없음.

## 무엇이 바뀌었나

SB: `sb postcompact-hook` + `tests/test_postcompact_hook.py` (Claude 2.1.261 `PostCompact` → `SearchIndex` → `additionalContext`).

JARVIS 바이트: 변경 없음 (`1672626`).

## 핀 (섞지 말 것)

- **새 소스/아카이브:** 이 커밋 이후 `git archive` 경로 (아래). 실행 핀 이름 재사용 금지
- **변경 없는 실행 핀:** `f7c1945` / wheel `1847b599…` / `/var/tmp/sb-gates-f7c1945.log` — **이번 훅 없음**
- **직전 아카이브:** `e13cd3b` / `d9c6825b…` — 훅 없음
- **운영 current:** 스냅샷 `41f0751` — 후보 아님

## 자체 검증

```
uv run pytest -q tests/test_postcompact_hook.py
# 4 passed
uv run ruff check sb/postcompact_hook.py sb/cli.py tests/test_postcompact_hook.py
# All checks passed
```

전체 회귀 미반복. native Claude 훅 미실행.

## 검토 경로

1. 이 문서와 `GROK-M9-SESSION-COMPACTION-CONSTRAINT-2026-09-13.md`
2. `GROK-CURRENT-OPERATIONS-REVIEW-2026-09-13.md`
3. 새 후보 `bin/sb postcompact-hook` (아카이브 후 절대 경로)
4. 테스트 파일 4건: 정상 본문/출처/예산, PreCompact 거부, 질의 실패가 성공 JSON이 아님, CLI stdout 계약

전체 A–F/M1–M14 인수가 아님.
