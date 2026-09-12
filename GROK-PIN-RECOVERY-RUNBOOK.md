# 핀 복구 런북 (운영 전환 아님)

**current를 바꾸지 않는다.** 운영 current는 `41f0751`.

## Full pin

```bash
source /var/tmp/sb-jarvis-restore-qku1N6/recovery.env
export REL=/var/tmp/sb-candidate-cf1c021/releases/9680e4fe7f1ea81ea81031bebbea8700346c12c3
export JARVIS=/var/tmp/jarvis-artifact-1672626/source/dist
```

| 항목 | 값 |
|---|---|
| SB source | `cf1c021dfa9fb15ac5dffbe619e42f6d3cdf4186` |
| git archive | `scripts/seed-scoped-v4.py` 포함 |
| wheel | `8f7a8420bb790ef52dec3d557eb5c5a5bdda4bd5df9b312c9c7f7a088bf88948` |
| JARVIS | `1672626c5f2b0b06f7fb93c900cf8771536b58cd` |
| inventory | `e9751dfaf955bab6a1ea15792733e0af576f7bac540ca5efeb0b69d9bccbf9cd` / 34768 |
| production_activated | false |

BACKUP는 seq3 high-water `jarvis-highwater.sqlite`다. 필수 SB restore와 만료 fence 거부 뒤에만 schema4 classified write를 증명한다.

## 종료 후

```bash
source "$ROOT/recovery.env"
node scripts/issue-restore-fence.mjs
uv run python scripts/restore-probe.py restore "$ROOT" < "$FENCE"
```

만료 fence는 `TOMBSTONE_FENCE_REQUIRED`가 정상 거부. 필수 restore 실패는 gate 실패.

## 게이트

```bash
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
```
