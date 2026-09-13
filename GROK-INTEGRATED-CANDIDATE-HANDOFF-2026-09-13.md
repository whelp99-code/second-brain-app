# 통합 고정 후보 — 46a3d60 Q1

검토자: Claude 야간. 운영전환/push 없음. 한정 인수 범위의 비차단 Q1.

| 역할 | 값 |
|---|---|
| 제품 | `8d1f8cc` 6자 미만 토큰은 단어 경계 hit만 가중 |
| SB 후보 | `/var/tmp/sb-candidate-8d1f8cc/releases/2ccf0267e52da2482d215b1e47dc6bf3f0fbd0e3` wheel `60d66ad6…` |
| J 런타임 | `/var/tmp/jarvis-artifact-64715ba` ≠ authority current |
| 게이트 로그 | `/var/tmp/sb-gates-f7c1945.log` 이 후보 아님 |

검증: pytest 30; ruff 0. `Later` ⊂ `ThetaLaterTarget`가 OmegaInturnTarget을 앞세우지 않음. sb search AND 불변. native 미실행.
