# 통합 고정 후보 — a47f2a9 B5/B2b

검토자: Claude 야간. 운영전환/push 없음.

| 역할 | 값 |
|---|---|
| 제품 | `f475adb` term-ranked hook search + SessionStart compact epoch |
| SB 후보 | `/var/tmp/sb-candidate-f475adb/releases/b277adcc789a27aa4f69b8525acca9100d61763e` wheel `35ea4274…` |
| J 런타임 | `/var/tmp/jarvis-artifact-64715ba` ≠ authority current |
| 게이트 로그 | `/var/tmp/sb-gates-f7c1945.log` 이 후보 아님 |

검증: pytest 24; ruff 0. 다중 단어 요약/프롬프트 `OmegaInturnTarget`. sb search AND 미변경. native 미실행. `M9_native_session` not_complete.
