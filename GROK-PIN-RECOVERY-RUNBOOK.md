# 핀 복구 런북 (운영 전환 아님)

**current를 바꾸지 않는다.**

## Full pin

```bash
source /var/tmp/sb-jarvis-restore-BXtuTK/recovery.env
export REL=/var/tmp/sb-candidate-4536718/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1
```

| 항목 | 값 |
|---|---|
| SB source | `4536718e68d8d65a24e1a459cb845d86f8c191f2` |
| wheel | `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57` |
| JARVIS | `1672626c5f2b0b06f7fb93c900cf8771536b58cd` |
| inventory | `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd` / 34768 |
| backup.js | `3137b3dece9363c69f3b0936fee8659e8e5f5c2e4d3d97457c3a77956e0fe3c4` |
| production_activated | false |

## 종료 후 fresh fence

```bash
source "$ROOT/recovery.env"
node scripts/issue-restore-fence.mjs
python scripts/restore-probe.py restore "$ROOT" < "$FENCE"
python scripts/writer-lease-on-root.py "$ROOT"
node scripts/restore-jarvis-sqlite.mjs
```

없는 dest는 COPYFILE_EXCL로만 게시한다. 검사 후 생긴 DB는 덮지 않고 거부한다.

## 게이트

```bash
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
```
