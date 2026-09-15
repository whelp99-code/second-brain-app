# 통합 고정 후보 — H5/H6 readiness (2026-09-15)

운영 current는 `8ea65a7d…` 불변. 이 후보는 격리. push 없음. 운영 DB 손수정 없음.

| 역할 | 값 |
|---|---|
| 제품 | `45f5b72` orphan activation sweep + superseded brief |
| 격리 후보 | `/var/tmp/sb-candidate-45f5b72/releases/62ffbc9d8267f142c2f86dd2c38af6dc5efd2028` |
| wheel | `acc4c80e120214707337349d1488d16756b801bc7632b22d8c195d1b35a19ce1` |
| 운영 SB current | `8ea65a7d…` 불변 |

## 실측

- `tests/test_orphan_activation_sweep.py` + `tests/test_supersede_brief_failures.py` + `tests/test_activated_orphan_rows.py` **9 passed**
- related readiness/store/ops **63 passed**
- ruff 0

H5: `maintain`이 current가 아니고 디렉터리/핀이 없는 `activated` 행을 `proved` + `disposal_digest`(`orphan-missing-directory`)로 전이.
H6: 이후 brief `done`이 있으면 실패 brief를 `superseded`로 전이(행 삭제 없음). `sb maintain --once`가 `settle_superseded_briefs`를 호출.
