# 통합 고정 후보 — 069aeaa N2a/N2b/N4

Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. N1 native/in-turn 모델요청 한계 유지. 운영전환/push 없음.

| 역할 | 값 |
|---|---|
| SB 소스 | `b9844efa06d0` |
| SB 후보 | `/var/tmp/sb-candidate-b9844ef/releases/3ae0a9a4c6db8934a814298f2ee741acc15c8349` wheel `f9429a95…` |
| JARVIS | `64715ba` `/var/tmp/jarvis-artifact-64715ba/bin/jarvis` `--help` 0 |
| AUTH_DB | `/home/jm/.local/state/orca-jarvis/jarvis.sqlite` |
| 운영 current | 41f0751 인용만 |

검증: pytest 14; 기존 J10/dispatch3 보존(JARVIS 바이트 미변경); ruff 0.

복구: 구버전 current/바이너리 start 금지. `sb restore <archive> --to <격리>`.
