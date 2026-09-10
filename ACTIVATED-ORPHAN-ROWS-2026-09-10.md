# 운영 `activated` 잔여 3행 — 원인

[인계 보완](CODEX-REPLY-REVIEW-2026-09-10.md) 5.4, [쓰기 비용](WRITE-COST-AND-INTERRUPT-2026-09-10.md) §4. 운영 journal은 읽기 전용. 행을 고치거나 `remember`를 돌리지 않았다.

관측 시각: 현재 세대 `sbgen:v1:8dbef8a6877a232b46ff75b8b97c30f439010f94c14dd0f601d84beb248b36ea`는 **proved** (`updated_at=2026-09-10T11:01:17.192Z`). `activations` 집계: proved 89, activated 3.

| generation_id (끝 12자) | updated_at | 세대 디렉터리 | 현재 포인터 |
|---|---|---|---|
| `…eeea2a91` | 2026-09-04T23:59:59.976Z | 없음 (active/retired 모두) | 아님 |
| `…b9abce65` | 2026-09-07T12:24:35.365Z | 없음 | 아님 |
| `…0e05fe` | 2026-09-10T03:37:49.339Z | 없음 | 아님 |

세 행 모두 `reader_drain_digest`/`disposal_digest` NULL.

## 격리에서 다음 쓰기가 정리한 이유

후보 `c04dee1`의 `GenerationMutationService.mutate`는 후속을 만들기 **전에** 현재 parent에 `store.activate(parent, None, …)`를 호출한다. 주석: 포인터만 바뀐 세대를 그대로 두면 predecessor가 영구 고아가 된다. 격리 실험의 잔여는 **그때의 current**였으므로 다음 `remember`가 그 행을 `proved`로 끝냈다.

## 운영에서 남는 이유

1. 운영 wheel `41f0751`의 `generation_runtime.py`에는 이 “finish prior pointer switch” 문구가 **없다**. 후보에만 있다.
2. 설령 후보로 전환해도, 그 호출은 **현재 parent만** 끝낸다. 위 3행은 이미 current가 아니다. 디렉터리도 없다. 다음 쓰기가 이 journal 행을 UPDATE하지 않는다.

상태 기계 SQL이 양쪽에 있다는 [쓰기 비용](WRITE-COST-AND-INTERRUPT-2026-09-10.md) 관찰은 유지한다. “정리 코드 부재”가 아니라 **현재가 아닌 activated 고아 행을 훑는 경로가 없다.** 후보 전환만으로 이 3행이 사라진다고 보지 않는다.

운영 journal을 수동으로 `proved`로 고치지 않는다. 고아 행 sweep은 별도 설계·회귀가 필요하다.

JSON: [ACTIVATED-ORPHAN-ROWS-2026-09-10.json](ACTIVATED-ORPHAN-ROWS-2026-09-10.json).
