# 통합 고정 후보 — 3차 운영 전환 (2026-09-15 18:41 KST)

| 역할 | 값 |
|---|---|
| 제품 | `45f5b72` |
| 소스 핀 | `a5c4159` |
| 운영 SB current | `62ffbc9d8267f142c2f86dd2c38af6dc5efd2028` (18:41 KST 전환) |
| 이전 current | `8ea65a7d…` 보존 |
| wheel | `acc4c80e120214707337349d1488d16756b801bc7632b22d8c195d1b35a19ce1` |

## readiness

- `GENERATION_CLEANUP_STALLED` 해소.
- 잔여 `LAST_RUN_UNSUCCESSFUL` · `DERIVATIONS_FAILED`(compile 2행)는 Codex 한도(2026-09-19 17:11 KST) 외부 원인.

H5: `maintain`이 current가 아니고 디렉터리/핀이 없는 `activated` 행을 `proved` + `disposal_digest`(`orphan-missing-directory`)로 전이.
H6: 이후 brief `done`이 있으면 실패 brief를 `superseded`로 전이(행 삭제 없음).
