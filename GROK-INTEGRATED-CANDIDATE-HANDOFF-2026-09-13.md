# 통합 고정 후보 인계 — a48cd07 N1–N4 후속

지정 검토: Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. 운영전환/push/인증복사/실사용자삭제 없음.

## 핀 표 (섞지 말 것)

| 역할 | 값 |
|---|---|
| 이번 SB 소스 | 이 커밋 (postcompact stage + UserPromptSubmit) |
| 이번 JARVIS 소스 | `a3c111cd0774eedfd6e2015cb6f0a1c5fff56cfe` |
| JARVIS dist | `/var/tmp/jarvis-artifact-a3c111c/dist` (`cli.js` 존재, `executeMemoryPostcompact` 포함). 빌드 metadata `source_head=a3c111c`, `source_dirty=true`는 커밋되지 않은 `AGENTS.md`뿐. 제품 트리에 없음 |
| JARVIS source archive | `/var/tmp/jarvis-artifact-a3c111c/source` |
| 이전 JARVIS dist | `1672626` / `f6757ce` — **이번 호스트 구성·event ledger 없음**. 게이트/실행 핀으로 재사용 금지 |
| 이전 SB 실행 핀 | `f7c1945` / wheel `1847b599…` / `/var/tmp/sb-gates-f7c1945.log` — 이번 훅 없음 |
| 직전 SB 후보 | `6110830` / `2cc28b41…` / wheel `50417180…` — PostCompact additionalContext 오인 버전 |
| 운영 current | 스냅샷 SB `41f0751`, authority `a3cbbbe` — 후보 아님 |

SB 새 격리 후보는 이 커밋 후 `deploy/prepare-release.py /var/tmp/sb-candidate-<short>` 결과로 채운다.

## 검사

- `uv run pytest -q tests/test_postcompact_hook.py` → 10 passed
- `uv run ruff check sb/postcompact_hook.py tests/test_postcompact_hook.py` → EXIT0
- basedpyright 해당 파일: 0 errors, 테스트 private/Any **경고 남음** (완전 통과 아님)
- `npx vitest run tests/integration/memory-postcompact.test.ts --no-file-parallelism` → 8 passed
- dispatch `-t 'sends once from a nested envelope|does not send a duplicate idempotency key|sends once when two nested dispatches'` → 3 passed / 21 skipped
- eslint 변경 파일 `--max-warnings=0` → EXIT0 (`_ignoredFence` void 처리)

native Claude/실모델 없음. 전체 A–F 인수 아님.
