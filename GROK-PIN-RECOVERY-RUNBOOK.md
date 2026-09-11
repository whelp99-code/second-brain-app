# 핀 복구 런북 (운영 전환 아님)

**current를 바꾸지 않는다.** 운영 current `41f0751` 유지는 구버전 호환 증거가 아니다.

## Full pin

```bash
REL=/var/tmp/sb-candidate-f921979/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1
JARVIS=/var/tmp/jarvis-artifact-e7088b3/source/dist
ROOT=/var/tmp/sb-jarvis-restore-PdT941
FENCE=$ROOT/trusted-fence.json
BACKUP=$ROOT/jarvis-authority-backup/jarvis-rehearsal.sqlite
```

| 항목 | 값 |
|---|---|
| SB source | `f921979d53b9bd14a1af6317d2e219c54723e541` |
| wheel | `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57` |
| JARVIS | `e7088b3e220698d50c5a4bd8a52e6f9f9283e491` |
| inventory | `a833c70b78560c24e237ba9627c29336cfd9ba14db2a453733322bae74ec371f` / 34768 |
| backup.js | `8e85f8c648aff78f223412628c4507c1c012dd14b487273c8972bd135a714bdc` |
| fixture config.toml | `f33d28b278a91dad8735c7ad8fe61e684e6522f343932c346453fc9806b0fd14` |
| JARVIS authority backup | `eb35bb6f27dc553793391ee1aed3b0f3ec3b147fd90a31168aa10ff080b89a67` |
| production_activated | false |

## 같은 fixture 복구 명령

신뢰 fence는 harness가 `$FENCE`에 쓴다. stdin으로 전달한다.

```bash
# SB restore (anchor 있는 runtime-backup)
python scripts/restore-probe.py restore "$ROOT" < "$FENCE"

# writer lease ≠ 빈 큐
python scripts/writer-lease-on-root.py "$ROOT"

# JARVIS sqlite restore (격리 backupSqlite 산출물)
# dest는 운영 ~/.local 이 아닌 fixture 경로만
node --input-type=module -e "
import {restoreSqlite} from '$JARVIS/src/personal-os-backup.js';
restoreSqlite({backupPath: process.env.BACKUP, destPath: process.env.DEST});
"
```

새 ROOT를 만들지 말고 위 `$ROOT`를 이어 쓴다. 재생성은:

```bash
TMPDIR=/var/tmp node scripts/jarvis-restore-acceptance.mjs "$JARVIS"
```

## 안전 거부

- 원본 anchor 없음: `RESTORE_SOURCE_ANCHOR_MISSING`
- 비 sqlite 백업: `E_RESTORE_FAILED`
- 운영 경로 backup/restore: `E_BACKUP_PATH` / `E_PROTECTED_ROOT`
- 구버전 rollback, revocation store를 못 읽는 대상: `check-rollback-compat.py` `allowed:false`

## Writer lease

`scripts/writer-lease-on-root.py`는 `generation.lock` exclusive를 잡은 뒤 두 번째 획득이 `GENERATION_WRITER_BUSY`인지 본다. `queue_depth>0`이고 `empty_queue=false`다. pipeline `.sb/run.lock` already_running/빈 큐와 구분한다.

## 게이트

```bash
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
```
