# 핀 복구 런북 (운영 전환 아님)

**current를 바꾸지 않는다.**

## Full pin

```bash
source /var/tmp/sb-jarvis-restore-7NTURy/recovery.env
export REL=/var/tmp/sb-candidate-d4759bc/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1
# recovery.env: ROOT BACKUP DEST FENCE AUTHORITY AUTHORITY_ROOT JARVIS
# AUTHORITY is a copy under ROOT/recovery-authority, not the harness tmp db
```

| 항목 | 값 |
|---|---|
| SB source | `d4759bcf67749ada6b3bd354bf48429c8f08a0fb` |
| wheel | `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57` |
| JARVIS | `b9ccc546ab9d4d537e17918a68eacf4ecb98f94c` |
| inventory | `1d041d0acd2bc10d24c2491dee9835d231a0f6e63dd14b75f8db886cc6a8721d` / 34768 |
| backup.js | `a357e2cb5cbeae98a8a6c2f3294f6c0be53a02543ad58b0e743a492f1261e042` |
| production_activated | false |

## 종료 후 fresh fence

harness `closeMemoryDatabase`는 tmp authority를 지운다. 런북 AUTHORITY는 `$ROOT/recovery-authority/` 복사본이다.

```bash
source "$ROOT/recovery.env"
node scripts/issue-restore-fence.mjs
python scripts/restore-probe.py restore "$ROOT" < "$FENCE"
python scripts/writer-lease-on-root.py "$ROOT"
node scripts/restore-jarvis-sqlite.mjs
```

## dest exclusive restore

기존 dest는 exclusive lock을 유지한 채 backup을 clone한다. checkpoint 후 close/park 공백이 없다. busy dest는 거부하고 writer COMMIT을 보존한다.

## 게이트

```bash
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
```
