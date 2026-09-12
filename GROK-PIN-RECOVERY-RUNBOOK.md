# 핀 복구 런북 (운영 전환 아님)

**current를 바꾸지 않는다.**

## Full pin

```bash
source /var/tmp/sb-jarvis-restore-rz8Ngm/recovery.env
export REL=/var/tmp/sb-candidate-2927afc/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1
# recovery.env already exports ROOT BACKUP DEST FENCE AUTHORITY AUTHORITY_ROOT JARVIS
```

| 항목 | 값 |
|---|---|
| SB source | `2927afcb10290a180a66190048664bec48d340cd` |
| wheel | `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57` |
| JARVIS | `dcf19bebf8863aeb17dd42e4b5a3da07416d89ee` |
| inventory | `0e5267bf9d072d53726ee8b76e2665fa0dd46c48c385e83fe0c698158bb16af2` / 34768 |
| backup.js | `da7ff61065ad67664486491ea3b2287c45362a785edee40f63dbaf991d69f00b` |
| production_activated | false |

## 만료 후 fresh fence

저장된 fence 파일은 최대 5분이다. 나중에 복원하려면 재발급한다. 키를 다시 등록하지 않는다.

```bash
source "$ROOT/recovery.env"
export REL
node scripts/issue-restore-fence.mjs
python scripts/restore-probe.py restore "$ROOT" < "$FENCE"
python scripts/writer-lease-on-root.py "$ROOT"
node scripts/restore-jarvis-sqlite.mjs
```

`issue-restore-fence.mjs`는 `JARVIS`, `AUTHORITY`, `AUTHORITY_ROOT`, `FENCE`가 없으면 EXIT 1이다.

## SQLite 세트

`restoreSqlite`는 dest exclusive lock 후 main/WAL/SHM을 한 세트로 park하고 검증된 backup만 dest로 올린다. busy dest는 거부하고 원본 세트를 유지한다. WAL을 잠금 없이 지우지 않는다.

## 게이트

```bash
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
```
