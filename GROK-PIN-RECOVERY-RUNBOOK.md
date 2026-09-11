# 핀 복구 런북 (운영 전환 아님)

후보를 재현하거나 실패 핀에서 되돌릴 때. **current를 바꾸지 않는다.**

## 현재 핀

SB `39ce670` 후보 `/var/tmp/sb-candidate-39ce670/releases/0ecdb561…` wheel `0e32b787…` × JARVIS `2a95f72` `/var/tmp/jarvis-artifact-2a95f72/source/dist` inventory `452bf352…` / 34768. dispatch JS `246bca54…`. 운영 current `41f0751`. `production_activated=false`.

## 성공 / 실패 조건

성공: `npx tsc --noEmit` EXIT 0, clean `rm -rf dist` 후 `npm run build`의 JS가 제출 dist와 같고, 설치 standard/work/maintenance 3게이트 EXIT 0, GJC dispatch 집중 테스트 통과, 정본 paired restore EXIT 0.

실패: tsc EXIT 2를 옛 dist로 덮음, helper/stub EXIT 0을 M6/M12 인수로 사용, `RESTORE_SOURCE_ANCHOR_MISSING` 우회, 운영 current 변경.

## 구버전 / 복구 준비

운영 current `41f0751`은 바꾸지 않는다. 격리 복구는 runtime-backup + `.recovery` journal 형식이다. 원본 anchor 없는 복원은 `RESTORE_SOURCE_ANCHOR_MISSING`으로 거부한다. 해시 예외로 우회하지 않는다.

검증된 격리 복구:

```bash
python scripts/restore-probe.py backup "$ROOT"
python scripts/restore-probe.py journal-loss-from-backup "$ROOT"
# JARVIS fence stdin →
python scripts/restore-probe.py restore "$ROOT"
node scripts/jarvis-restore-acceptance.mjs "$JARVIS_DIST"
```

결과의 `rpo_sb.crash_loss_records`, `rto.restore_to_readable_ms`, `rto.failure_to_work_available_ms`를 사용한다. `scenario_ms`는 전체 시나리오 시간이며 RTO가 아니다.

## V1 세션 compaction (외부 조건)

JARVIS CLI에는 모델 세션 문맥 compaction 이벤트가 없다. 제품 경로는 `gjc.connect`/`configureGjc`로 세션을 만든 뒤 명시적 `gjc.dispatch`다. 자료삭제/correction-lane compaction은 이 trigger가 아니다. native/Orca 세션 제품이 compact/new-session에서 dispatch를 호출해야 하며, 그 입력은 이 후보에서 `blocked_external`이다.

## JARVIS 클린 빌드

```bash
cd /home/jm/orca/projects/Orca-JARVIS
rm -rf dist
npx tsc --noEmit -p tsconfig.json
npm run build
```

dist에 `reader.revalidate`와 `captureFromReference` 경로가 있어야 한다. 옛 dist를 rsync로 덮지 말 것.

## 게이트

패키지 핀의 `REL`과 `JARVIS` 경로를 사용한다.

```bash
TMPDIR=/var/tmp python deploy/check-release-maintenance.py "$REL"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS"
TMPDIR=/var/tmp python deploy/check-release-integration.py "$REL" "$JARVIS" --work REAL-WORK-ITEM-2026-09-10.json
```
