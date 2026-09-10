# 전환 런북 — 후보 `14a6ed7` (실행하지 않음)

W3.5. **이 문서는 전환을 실행하지 않는다.** 관측 `2026-09-10T13:59:10.032100+00:00`. `drain_authorized=false`, GJC unexpired lease 1, `jm-jarvis`/`dashboard`/`phone-gateway` active. 새 JARVIS dependency artifact 없음.

## 대상 / 롤백

| | 지금 운영 | 전환 목표 | 실패 시 |
|---|---|---|---|
| SB `current` | `41f0751aca8906d612961e704bc60dd0855fdabd` | 검증된 복사본 `14a6ed7ce284fa24a4e8157b97302f5d5786a275` (원본 `/var/tmp/sb-candidate-8de4c6b/releases/14a6ed7…`) | 링크를 `41f0751…`로 |
| `provider_release_sha` | `41f0751…` | `14a6ed7…` | 설정 백업과 함께 |
| JARVIS authority | `a3cbbbe…` / `7023f7c` | **바꾸지 않음** — 페어 `195b1a7` dist를 운영 CC에 섞지 않음 | — |
| 활성 세대 | `sbgen:v1:23fdff0d…` proved, `.sb/compiled` 없음 | 포인터 유지. 첫 compile은 W1 dest 복구 | 세대 디렉터리 삭제 금지 |

비교 기준 후보는 계속 `c04dee1` / wheel `ac8fcd16…`.

## 허가 전까지 금지

큐 0 ≠ writer 배제. 정지 후 `check-database-handles.py`와 SB `run.lock`을 다시 본다. 오래된 PID를 재사용하지 않는다. 전환 직전 SB tarball + JARVIS `--production` 백업 SHA를 이 표에 추가한다. 이번 SB 파일 백업은 `second-brain-20260910T032857+0900.tar.gz`.

스키마: 후보 `14a6ed7`는 운영 wheel에 `revoked-jarvis-signing-key-ids`와 doctor warn을 더한다. 링크만 `41f0751`로 되돌리면 새 state 파일은 남는다. 그 파일은 설정 복원이 아니라 state_root다.

## 전환 창에서만 (아직 아님)

1. 이 런북을 대상으로 중단 판단을 받는다.
2. path/timer 정지, pending 0, lease 처리, DB 핸들 0.
3. 릴리스 디렉터리를 `app/releases/14a6ed7…`로 복사하고 wheel SHA를 재확인.
4. `current` 링크 교체, `provider_release_sha` 갱신.
5. 실제 principal로 동일 업무 ID 종단. activation 성공만으로 M1–M7 완료가 아니다.

첫 compile 전 compiled marker 없는 세대는 W1 규칙을 따른다. 고아 `activated` 3행은 자동 `proved`가 아니다.
