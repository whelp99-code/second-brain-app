# 통합 고정 후보 — e0b3445 N4 문서

Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. 제품 재수정 없음. N2 통과분 유지. N1 한계 유지. 운영전환/push 없음.

| 역할 | 값 |
|---|---|
| 제품 | `a41b70d` |
| 테스트 전용 | `e0b3445` |
| 이 문서 | 이 커밋 |
| SB 후보 | `/var/tmp/sb-candidate-a41b70d/releases/c9bdc5dd520b0e3908207cf34f319799e48bb19a` |
| J 런타임 | `/var/tmp/jarvis-artifact-64715ba` ≠ authority current |
| AUTH_DB | `/home/jm/.local/state/orca-jarvis/jarvis.sqlite` |
| 게이트 로그 | `/var/tmp/sb-gates-f7c1945.log` (이 후보 아님) |
| 운영 current | 41f0751 인용만 |

리포 unit: `systemd/user/jm-second-brain-requests.path` **PathChanged**; service **ConditionPathIsDirectory** + `/usr/bin/env sb apply-requests --once`.
