# 전환 런북 — 후보 `0eefce7` (실행하지 않음)

게이트된 최신 격리 후보. **전환을 실행하지 않는다.** 관측: `drain_authorized=false`, GJC unexpired lease 1. 활성 세대 `sbgen:v1:a3bebcd3…`, `.sb/compiled` 없음. 운영 SB `41f0751`.

이전 런북 [14a6ed7](CUTOVER-RUNBOOK-14a6ed7-2026-09-10.md)은 W6 없는 wheel이다. 비교 기준 `c04dee1`은 유지.

| | 지금 운영 | 전환 목표 | 실패 시 |
|---|---|---|---|
| SB `current` | `41f0751…` | 복사본 `0eefce70378a2b0051ee0d8c159a542d1fd9f554` (원본 `/var/tmp/sb-candidate-f142a76/releases/0eefce7…`, wheel `dc705e8a…`) | `41f0751…` |
| `provider_release_sha` | `41f0751…` | `0eefce7…` | 설정 백업 |
| JARVIS | `a3cbbbe` / CC `artifact-4146a` | **바꾸지 않음** | — |

허가 전: 큐 0 ≠ 배제. 새 JARVIS artifact 없음. `revoked-jarvis-signing-key-ids`는 state_root에 남는다. 고아 `activated` 3행은 자동 정리되지 않는다. 첫 compile은 W1 dest 규칙.

`--work`/유지보수 EXIT 0은 [W3-WORK-GATE-0EEFCE7](W3-WORK-GATE-0EEFCE7-2026-09-10.md), [W3-GATES-0EEFCE7](W3-GATES-0EEFCE7-2026-09-10.md).
