# 현재 후보 운영 판단 (읽기 전용, 미실행)

전환·restore·rollback·경합 검사를 실행하지 않는다.

## 알려진 피연산자

| 이름 | 값 |
|---|---|
| SB 후보 | `/var/tmp/sb-candidate-7cc5fbc/releases/99746496b854f6fb42b69466bebca58149bb9396` |
| J 런타임 | `/var/tmp/jarvis-artifact-64715ba` |
| SB_CURRENT | `/home/jm/.local/state/second-brain/app/current` |
| J_CURRENT | `/home/jm/.local/state/orca-jarvis/authority/current` |
| AUTH_DB | `/home/jm/.local/state/orca-jarvis/jarvis.sqlite` |
| SB_CONFIG | `/home/jm/.config/second-brain/config.toml` |
| request pending | `/home/jm/.local/state/second-brain/requests/pending` |
| request-executor.enabled | `/home/jm/.config/second-brain/request-executor.enabled` |
| refresh.env | `/home/jm/.config/jm-second-brain/refresh.env` |

`state_root` ≠ `request_root`. `request_root` 미설정 시 `$XDG_STATE_HOME/second-brain/requests`.

lock:
- pipeline: **실행 root** `vault_root/.sb/run.lock` (`pipeline.py`; 스테이징 시 스테이징 root)
- generation: `$state_root/generation.lock` + `$state_root/generation-writer.lock`

## 공개 activator

| 유닛 | 역할 | 기동 조건 |
|---|---|---|
| `jm-second-brain-requests.path` | pending 비면 requests.service | `ConditionPathExists=request-executor.enabled`, `DirectoryNotEmpty=…/requests/pending` |
| `jm-second-brain-requests.service` | oneshot `$SB_CURRENT/bin/sb apply-requests --once` | path가 기동 |
| `jm-second-brain-refresh.timer` | 07:00 Asia/Seoul | `Unit=jm-second-brain-refresh.service` |
| `jm-second-brain-refresh.service` | `${SECOND_BRAIN_REFRESH_ENTRYPOINT}` from refresh.env | timer |
| `second-brain.timer` | hourly `second-brain.service` | `PATH sb run` — current/bin과 다를 수 있음 |
| `jm-jarvis.service` | `node $J_CURRENT/dist/src/cli.js service run --db $AUTH_DB` | |

## 관측 (전환 조건 아님)

`readlink -f $SB_CURRENT $J_CURRENT`; `which -a sb`
`systemctl --user is-active` 위 유닛+dashboard+phone-gateway+refresh.timer
`python3 deploy/check-jarvis-pending-state.py "$AUTH_DB"`
`python3 deploy/check-database-handles.py "$AUTH_DB"`

## stop (승인 후)

`systemctl --user stop jm-jarvis.service jm-jarvis-dashboard.service jm-jarvis-phone-gateway.service jm-second-brain-refresh.timer jm-second-brain-refresh.service jm-second-brain-requests.path jm-second-brain-requests.service second-brain.timer second-brain.service`

**정지 사후조건 (실패 시 ln 금지, 정지 유지):**
- handles `"$AUTH_DB"` EXIT0
- pending-state 관측 (`drain_authorized` false)
- `$state_root/generation-writer.lock` 및 **실행 root** `.sb/run.lock` 홀더 없음
- requests.path inactive

## current

`ln -sfn <SB후보> $SB_CURRENT`
`ln -sfn <J후보/authority release> $J_CURRENT`

**부분 상태 (이전 current 유지가 아님):**
- SB ln 성공·J 실패: SB=후보, J=옛 current. start 금지.
- J ln 성공·SB 실패: 대칭. start 금지.
- restore 후: `sb restore <archive> --to <격리>`만. 격리 config의 vault_root/state_root/request_root를 명시한 뒤에만 검증. 검증 전 writer 정지 유지. `--force` 당일 승인 없이 금지.
- 구버전 바이너리/`41f0751` start 금지.

start는 새 current 절대 경로만. 성공: `$SB_CURRENT/bin/sb doctor`; `$SB_CURRENT/bin/sb search` 1건; `$J_CURRENT` 서비스 active; `/var/tmp/jarvis-artifact-64715ba/bin/jarvis --help` 0.

보류 수명 미검증.
