# 핀 복구 런북 (운영 전환 아님)

후보를 재현하거나 실패 핀에서 되돌릴 때. **current를 바꾸지 않는다.**

## 현재 핀

SB `8d80a3a` 후보 `/var/tmp/sb-candidate-8d80a3a/releases/0ecdb561…` wheel `0e32b787c97a42d922132e93e3c67ab375d06154b433d23a042283112cbf0b57` × JARVIS `f9e0791` `/var/tmp/jarvis-artifact-f9e0791/source/dist` inventory `650c79d62cba1c27c1db06cf403f8bd2ffa73dffd45f7290148dc86b655f826e` / 34768. dispatch JS `8d95e3d41880bdece0585a42242ccfa0ed82062c9e44577a63b523ff144d8456`. 운영 current `41f0751`. `production_activated=false`.

## 서비스·설정·백업 해시 (소스, 운영 설치 아님)

| 파일 | sha256 앞 16자 |
|---|---|
| deploy/systemd/second-brain.service | `40db7e1eb09a3aa7` |
| deploy/systemd/second-brain-web.service | `e0de89ea1b3f386e` |
| deploy/systemd/second-brain-backup.service | `7fa64a3f6505565b` |
| deploy/systemd/second-brain.timer | `c00386c8aa07eed0` |
| deploy/systemd/second-brain-backup.timer | `f55b568be19969bd` |
| deploy/install-systemd-user.sh | `6b4bef87c5c140e3` |
| deploy/check-rollback-compat.py | `7b1ec32bd66d34b2` |

구버전 호환: 운영 `41f0751` 유지. 격리 복원은 runtime-backup + `.recovery` journal. 원본 anchor 없으면 `RESTORE_SOURCE_ANCHOR_MISSING`. 해시 예외로 우회하지 않음.

## 성공 / 실패 조건

성공: `npx tsc --noEmit` EXIT 0, clean `rm -rf dist` 후 `npm run build` JS가 제출 dist와 같고, 설치 3게이트 EXIT 0, GJC dispatch 집중 통과, same-content 2 evidence_id.

실패: tsc EXIT 2를 옛 dist로 덮음, helper EXIT 0을 인수, `RESTORE_SOURCE_ANCHOR_MISSING` 우회, 운영 current 변경.

## V1 세션 compaction (외부 조건)

JARVIS CLI에는 모델 세션 문맥 compaction 이벤트가 없다. 제품 경로는 `gjc.connect`/`configureGjc` 후 명시적 `gjc.dispatch`. 자료삭제 compaction은 이 trigger가 아니다.

## 격리 복구

```bash
python scripts/restore-probe.py backup "$ROOT"
python scripts/restore-probe.py journal-loss-from-backup "$ROOT"
python scripts/restore-probe.py restore "$ROOT"
node scripts/jarvis-restore-acceptance.mjs "$JARVIS_DIST"
```

`rpo_jarvis.last_durable_at_ms`는 proved write 이후. `rto.failure_to_work_available_ms`는 scoped+new write. `scenario_ms`는 RTO가 아니다.

## JARVIS 클린 빌드

```bash
cd /home/jm/orca/projects/Orca-JARVIS
rm -rf dist
npx tsc --noEmit -p tsconfig.json
npm run build
```

dist에 `memoryEvidenceId`가 있어야 한다. 옛 dist를 덮지 말 것.

## 게이트

```bash
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
```
