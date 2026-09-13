# 통합 고정 후보 — b279068 N2/N3/N4

Codex `term_6bf51058-3b29-40e2-a25b-b751fab0c24e`. 운영전환/push 없음. N1 native/auto-compact 다음 모델요청은 공개 계약 없음.

| 역할 | 값 |
|---|---|
| SB 소스 | `6b01c2e6d29b` |
| SB 격리 후보 | `/var/tmp/sb-candidate-6b01c2e/releases/fc2507ed0c4246da550fc2971516077c4ee66cd7` wheel `c6278e7e…` |
| JARVIS 소스 | `64715bade176f5724bc4ebe8a40bc6f4c8f49a96` |
| JARVIS 실행 | `/var/tmp/jarvis-artifact-64715ba/bin/jarvis` `--help` 0. runtime node_modules는 `78e7307` lock 재사용. dist digest `sha256:c64cfbf1…` 1216 files |
| 이전 | b279068 / e02636e / FileModelTransport 성공 오인 / `current/jarvis-authority.sqlite` 금지 |
| AUTH_DB | `/home/jm/.local/state/orca-jarvis/jarvis.sqlite` (유닛 `--db`) |
| 운영 current | 41f0751 / a3cbbbe 인용만 |

검증: SB pytest 이번 훅; JARVIS 10 + dispatch 3; eslint 0; jarvis --help 0.

복구: 구버전 current/바이너리 start 금지. 새 릴리스 + restore --to.
