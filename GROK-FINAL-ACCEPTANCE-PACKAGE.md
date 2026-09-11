# Grok 최종 제출 — `0ecdb561` × JARVIS `bcb47af`

CODEX-NIGHT-REVIEW-1d3d1d7. **운영 전환 없음. 제품 인수 아님.**

## 핀

| | |
|---|---|
| SB source | `8db46c59f249ff2da483336c0ec3318e2d317859` |
| 후보 | `/var/tmp/sb-candidate-8db46c5/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1` |
| wheel | `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57` |
| JARVIS | `bcb47af` `/var/tmp/jarvis-artifact-bcb47af/source/dist` |
| JARVIS inventory | `964aeaa543b30c7bde6e2dfb988586261801979fd6669490052990dc5994d632` (34780) |
| tsc | EXIT 0. dist has `gjcWorkerAlive` |
| 운영 current | `41f0751` |
| production_activated | false |

## 재현

```bash
REL=/var/tmp/sb-candidate-8db46c5/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1
JARVIS=/var/tmp/jarvis-artifact-bcb47af/source/dist
cd /home/jm/orca/projects/Orca-JARVIS && rm -rf dist && npx tsc --noEmit -p tsconfig.json && npm run build
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
TMPDIR=/var/tmp uv run pytest -q --ignore=tests/test_embeddings.py
# 1832 passed, 2 skipped  /var/tmp/sb-full-pytest-8db46c5.log
```

## N1 / M6 / M12

| ID | 상태 | 증거 |
|---|---|---|
| N1 | verified 격리 | pending 예약에 `pid:` lease. 죽은 worker는 공개 `gjc.dispatch`가 다시 send. 살아 있는 동시 키는 send 1. deny/transport 재시도 보존 |
| M6 | implemented_unverified | 두 프로세스: held 중 `already_running=true`, kill 후 lock 회수. store-blind rollback `allowed:false`. cutover false. `/var/tmp/m6-writer-cutover.json` |
| M12 | implemented_unverified | sqlite 삭제 후 restore, 이후 `post-restore-needle` write. RTO 0.02s. `/var/tmp/m12-cold-restore-write.json` |

## M1–M14

| ID | 상태 |
|---|---|
| M1 | blocked_external 실로그인 |
| M2 | implemented_unverified `--work` |
| M3 | implemented_unverified |
| M4 | implemented_unverified fixture |
| M5 | blocked_external native. 인증 복사는 금지 |
| M6 | implemented_unverified 위 |
| M7 | implemented_unverified fixture |
| M8 | blocked_external native |
| M9 | implemented_unverified N1 |
| M10 | implemented_unverified N2 보존 |
| M11 | implemented_unverified Codex MCP 보존 |
| M12 | implemented_unverified 위 |
| M13 | implemented_unverified N4 보존 |
| M14 | not_implemented |
