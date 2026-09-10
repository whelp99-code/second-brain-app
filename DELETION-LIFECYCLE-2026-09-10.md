# 삭제 후 재등장 차단 — 현재 HEAD에서 재확인

인계서 8-C 인수 묶음 6번의 **삭제 절반**이다. 정정 절반은 [정정 공유](CORRECTION-SHARED-MEMORY-2026-09-10.md)에서 운영 경로로 확인했고, 이 문서는 삭제·복원 수명을 격리 경로에서 확인한다.

새로 만든 검사는 없다. 기존 `scripts/jarvis-restore-acceptance.mjs`가 이미 이 조건을 단정하고 있어, **오래된 보고서를 인용하는 대신 현재 HEAD에서 다시 실행해** 현재 상태 증거를 얻었다.

## 실행

```bash
TMPDIR=/var/tmp PYTHONPATH=. node scripts/jarvis-restore-acceptance.mjs \
     /var/tmp/jarvis-current-pair-_mq15nmd/source/dist
```

제품 HEAD `d1d06e2`, JARVIS 격리 빌드 `195b1a7`. **exit 0**, `model_calls: 0`.

## 단정된 수명

| 단계 | 관측 |
|---|---|
| 삭제 전 조회 | `DeleteAlpha` 1건 |
| 실제 자비스 효과 경로로 `forget` | `tombstone_sequence: 1` |
| **삭제 후 조회** | **0건** |
| 같은 시점 `KeepBeta` | 1건 — 삭제가 무차별이 아님 |
| 백업 복원 | `tombstone_sequence: 1`, `set_root: sha256:7a31d104…` — fence와 **동일**, 세대 `sbgen:v1:a768a58a…` |
| 복원 후 남은 기억 | 1건 (`first_restore_surviving_records`) |
| 복원 뒤 두 번째 `forget` | `tombstone_sequence: 2` |
| 두 번째 복원 | `tombstone_sequence: 2`, `set_root: sha256:a5bb1611…`, 세대 `sbgen:v1:39d94c0e…` |
| **두 번째 복원 후 조회** | `deleted_records: 0`, `second_restore_records: 0` — **둘 다 되살아나지 않음** |
| 자비스 보유 high-water | 2 |

핵심은 마지막 두 줄이다. **백업에서 복원해도 삭제된 기억이 돌아오지 않는다.** 복원이 삭제 high-water를 그대로 이어받기 때문이다. 삭제 → 복원 → 재삭제 → 재복원의 두 바퀴 모두에서 성립했다.

동시 접근도 같은 실행에서 확인됐다: 독립 클라이언트 2개, 독립 철회 2건, 복원된 기억이 두 클라이언트에서 동일(`shared_restored_memory_equal: true`).

## 한계

- **격리 fixture 경로다.** 원본·키·권한·프로젝트 범위가 모두 synthetic이며 운영 활성화가 아니다. 실제 stdio 제품 경로와 실제 시계를 쓰고 모델 호출은 0이다.
- **운영 기억의 삭제는 하지 않았다.** 운영 tombstone high-water를 되돌릴 수 없게 올리므로 사용자 승인이 필요하다. 이 문서의 증거를 운영 삭제 인수로 확대하지 않는다.
- native 세션·compaction·로그·WAL·백업 사본까지의 삭제 수명(M5)은 여전히 미완이다. 이 실행은 provider 기억과 그 백업/복원만 덮는다.
- 관련 단위 회귀도 같은 HEAD에서 확인했다: `tests/test_erasure.py`, `tests/test_reingress.py`, `tests/test_erasure_vectors.py`, `tests/test_ingest_reingress_failure.py`, `tests/test_correction_cancellation_executor.py` **20 passed / 14.45초**.

## 8-C 6번 현황

| 절반 | 상태 |
|---|---|
| 정정 후 이전 내용을 최신 사실로 쓰지 않음 | 운영 경로 완료 — Codex 저장, Claude 새 세션이 정정을 최신으로 판정 |
| 삭제 후 새 세션·복원에서 재등장 없음 | **격리 경로 완료** (이 문서) |
| 운영 경로의 실제 삭제 | 미완 — 사용자 승인 대기 |
