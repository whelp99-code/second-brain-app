# 핀 복구 런북 (운영 전환 아님)

후보를 재현하거나 실패 핀에서 되돌릴 때. **current를 바꾸지 않는다.**

## 현재 핀

SB `537ec9b` 후보 `/var/tmp/sb-candidate-537ec9b/releases/0ecdb561…` × JARVIS `a935751` `/var/tmp/jarvis-artifact-a935751/source/dist`. 운영 current `41f0751`.

## JARVIS 클린 빌드

```bash
cd /home/jm/orca/projects/Orca-JARVIS
rm -rf dist
npx tsc --noEmit -p tsconfig.json
npm run build
# dist에 model_send_started / unknown_accepted 가 있어야 한다. 옛 dist를 rsync로 덮지 말 것.
```

## 게이트

```bash
REL=/var/tmp/sb-candidate-537ec9b/releases/0ecdb5617a1fe95697e55366f631ee4373f407b1
JARVIS=/var/tmp/jarvis-artifact-a935751/source/dist
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
```

## 세션/compaction/public transport (V1)

격리: `gjc.dispatch` nested `{task, assemble_context}`. extra keys send 0. `model_send_started` 후 local receipt 없으면 재전송하지 않는다 (`recovered: unknown_accepted`). 죽은 pid + send 시작 전은 회수 후 send.

## DR

원본 journal 없으면 `RESTORE_SOURCE_ANCHOR_MISSING`. 해시 예외로 우회하지 않는다. 신뢰 journal로 `verified_restore_source` 후 제품 `run_all` write.
