# 핀 복구 런북 (운영 전환 아님)

**current를 바꾸지 않는다.** `41f0751` 유지는 구버전 호환 증거가 아니다.

## Full pin

```bash
source /var/tmp/sb-jarvis-restore-PbKSr3/recovery.env
export REL=/var/tmp/sb-candidate-a1a5ae2/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1
export JARVIS=/var/tmp/jarvis-artifact-22b4613/source/dist
# recovery.env already sets ROOT BACKUP DEST FENCE
```

| 항목 | 값 |
|---|---|
| SB source | `a1a5ae2a7e0495117790bf03f14a42bbbe67760c` |
| wheel | `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57` |
| JARVIS | `22b46139e312979e6ac81b41ef4b8c64a4d2d71a` |
| inventory | `6f30a34af67aec7587ef1bfdb046c29645cc0e5508030ce4be13d08711a7b868` / 34768 |
| backup.js | `9012c592e904311959e38bfaa7368623af98fc84b3de5a98fbf8b2fa3385215a` |
| production_activated | false |

## 같은 ROOT

`$FENCE`는 harness가 **마지막 high-water**에서 발급한 현재 fence다. 첫 restore의 fence1을 재사용하지 않는다.

```bash
source "$ROOT/recovery.env"
export REL JARVIS
python scripts/restore-probe.py restore "$ROOT" < "$FENCE"
python scripts/writer-lease-on-root.py "$ROOT"
node scripts/restore-jarvis-sqlite.mjs
```

`restore-jarvis-sqlite.mjs`는 `BACKUP`, `DEST`, `JARVIS`가 없으면 EXIT 1이다.

재생성:

```bash
TMPDIR=/var/tmp node scripts/jarvis-restore-acceptance.mjs "$JARVIS"
```

## 실패 보존

없는/junk backup은 기존 dest와 원본을 지우지 않는다. 검증된 staging만 dest로 rename한다. 같은 경로 restore는 거부. 정정 재시도는 유효 backup으로 dest를 교체한다.

invalid sqlite는 `E_RESTORE_FAILED`다. 구버전 스키마는 tombstone_chain 없는 sqlite로 구분한다.

## Writer lease

`pending_requests`는 `requests.state='pending'`이다. `journal.db` 파일 개수가 아니다. pending 0이어도 `writer_busy`일 수 있다.

## 게이트

```bash
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
```
