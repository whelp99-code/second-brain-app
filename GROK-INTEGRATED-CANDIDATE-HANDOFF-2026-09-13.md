# 통합 고정 후보 — a18396f B1–B4 + D1–D3

검토자: Claude 야간. 운영전환/push 없음.

| 역할 | 값 |
|---|---|
| 제품 | `5680155` SessionStart compact + last_query |
| SB 후보 | `/var/tmp/sb-candidate-5680155/releases/64274fd223c84bde58cde3c9029d3515062e4a40` wheel `c79ebc0b…` |
| J 런타임 | `/var/tmp/jarvis-artifact-64715ba` ≠ authority current |
| 게이트 로그 | `/var/tmp/sb-gates-f7c1945.log` 이 후보 아님 |

검증: pytest 21; ruff 0. 문서화된 SessionStart `{hook_event_name, source:compact, session_id}` (요약 없음) → last_query 또는 `{}` exit 0. source≠compact `{}` exit 0. native 미실행. `M9_native_session` not_complete.
