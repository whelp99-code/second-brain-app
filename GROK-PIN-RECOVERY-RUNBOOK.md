# 핀 복구 런북 (운영 전환 아님)

**current를 바꾸지 않는다.**

## Full pin

```bash
source /var/tmp/sb-jarvis-restore-Ar1cuM/recovery.env
export REL=/var/tmp/sb-candidate-12db06e/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1
export JARVIS=/var/tmp/jarvis-artifact-1672626/source/dist
```

| 항목 | 값 |
|---|---|
| SB source | `12db06edc6760f8478e2d7c866b10a8d06430eb3` |
| wheel | `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57` |
| JARVIS | `1672626c5f2b0b06f7fb93c900cf8771536b58cd` |
| inventory | `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd` / 34768 |
| production_activated | false |

BACKUP는 seq3 high-water `jarvis-highwater.sqlite`다. seq1 rehearsal는 RPO 측정용이다.

## 종료 후

```bash
source "$ROOT/recovery.env"
node scripts/issue-restore-fence.mjs   # seq 3
uv run python scripts/restore-probe.py restore "$ROOT" < "$FENCE"
```

만료 fence는 TOMBSTONE_FENCE_REQUIRED가 정상 거부. 필수 restore 실패는 gate 실패.

## 게이트

```bash
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
```
