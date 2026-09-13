# 통합 고정 후보 — 7de7c6f C1–C5

검토자: Claude 야간. 운영전환/push 없음.

| 역할 | 값 |
|---|---|
| 제품 | `bad60a6` last_query 가드, PostCompact 잔여, 희소 term 가중 |
| SB 후보 | `/var/tmp/sb-candidate-bad60a6/releases/18725677f61d5f4f3a1fe4e2ad2d8829927aaf32` wheel `60892449…` |
| J 런타임 | `/var/tmp/jarvis-artifact-64715ba` ≠ authority current |
| 게이트 로그 | `/var/tmp/sb-gates-f7c1945.log` 이 후보 아님 |

검증: pytest 28; ruff 0. continue/go on이 last_query를 덮지 않음. SessionStart가 PostCompact 잔여를 유지. 늦은 대상 토큰 검색. last_query는 파생 term. native 미실행.
