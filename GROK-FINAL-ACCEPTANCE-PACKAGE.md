# Grok 최종 제출 — `caba60cb` × JARVIS `ad2d645`

CODEX-NIGHT-REVIEW-a7df330. **운영 전환 없음. 제품 인수 아님.** 옛 `d564688`/`e51b068` 보존.

## 핀

| | |
|---|---|
| SB source | `15f8933439bd272f5e60839a88d2609b1d005164` |
| 후보 | `/var/tmp/sb-candidate-15f8933/releases/caba60cb6c304151a1e5f8e593723dbac286fa1d` |
| wheel | `ab258c894fd1827d569309dd05d66d50b345965391d184af1cbf2fbfb95979c2` |
| JARVIS | `ad2d645` `/var/tmp/jarvis-artifact-ad2d645/source/dist` |
| JARVIS inventory | `43438a602e055562ca8309857697264c5c2a187754c1da3b8d28d781bc2a1e98` (34778) |
| 운영 current | `41f0751` |
| production_activated | false |

## 재현

```bash
REL=/var/tmp/sb-candidate-15f8933/releases/caba60cb6c304151a1e5f8e593723dbac286fa1d
JARVIS=/var/tmp/jarvis-artifact-ad2d645/source/dist
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
# 1826 passed, 2 skipped  /var/tmp/sb-full-pytest-15f8933.log
```

## N1–N4 / MCP / DR / rollback

| ID | 상태 | 증거 |
|---|---|---|
| N1 | verified 격리 | `createProductionMemoryReference.deliverAssembled` persist 후 await send, 1회 재시도, 실패 시 MODEL_TRANSPORT_UNAVAILABLE. 거절 persist sent=0. JARVIS 3 passed |
| N2 | verified 격리 | 보존. 짧은 core가 quartz×4 긴 문서보다 앞 |
| N3 | verified 격리 | marker SHA-256. `key:other\\nkey:te` 절단 시 UNSAFE, key:test 재활성화 없음 |
| N4 | implemented_unverified | 보존. last_batch ok |
| MCP | implemented_unverified | 후보 MCP 30/100/300 p95 0.186s large. `M11-MCP-CORPUS-LATENCY-2026-09-11.json` |
| DR | implemented_unverified | 이전 sealed 회수 1. `R6-SEALED-RETRIEVE-2026-09-11.json` |
| rollback | verified 격리 | `tests/test_rollback_compat.py` 이번 회귀에 포함 |
