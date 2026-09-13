# 통합 고정 후보 인계 — 2026-09-13

지정 검토: Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. 제품 수정은 이 Grok 커밋. 운영전환/push/인증복사/실사용자삭제 없음. 보류 보안/삭제 분기 재실행 없음.

## 무엇이 바뀌었나

SB: `sb postcompact-hook` + `tests/test_postcompact_hook.py` (Claude 2.1.261 `PostCompact` → `SearchIndex` → `additionalContext`).

JARVIS 소스: `f6757ce` (`memory postcompact` + 합성 5 passed). 격리 `git archive`: `/var/tmp/jarvis-artifact-f6757ce/source`. 이전 dist `1672626`은 **이 진입점 없음**. 새 dist 빌드/운영 current 없음.

## 핀 (섞지 말 것)

- **새 소스:** `611083036f342f3590627723693d729898c25a0c` (`git-archive`)
- **새 격리 후보 (미활성):** `/var/tmp/sb-candidate-6110830/releases/2cc28b41fa0bb848cd551ed7b20e683857c05d85`
  - `bin/sb` 절대 경로 위 디렉터리. `sb postcompact-hook -h` EXIT 0
  - wheel SHA256 `50417180cd8f9a79d537b2f4774a8d96ff94c28c0370e7da8fce2b2df05be2c6` (**f7c1945 `1847b599…`와 다름**)
  - manifest `working_tree_modified: true` — 워크트리 dirty는 아카이브에 없음 (모니터 JSON). 제품 훅은 커밋 트리
- **변경 없는 실행 핀:** `f7c1945` / wheel `1847b599…` / `/var/tmp/sb-gates-f7c1945.log` — **이번 훅 없음**. 게이트 로그 이름 바꾸지 않음
- **직전 아카이브:** `e13cd3b` / `d9c6825b…` — 훅 없음
- **JARVIS:** `1672626` 변경 없음
- **운영 current:** 스냅샷 `41f0751` — 후보 아님. `current` 미교체

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
