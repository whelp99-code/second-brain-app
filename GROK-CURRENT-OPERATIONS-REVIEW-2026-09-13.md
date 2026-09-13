# 현재 후보 운영 판단 (읽기 전용, 미실행)

전환·restore·rollback을 실행하지 않는다.

## 변수

```
AUTH_DB=/home/jm/.local/state/orca-jarvis/jarvis.sqlite
J_CURRENT=/home/jm/.local/state/orca-jarvis/authority/current
SB_CURRENT=/home/jm/.local/state/second-brain/app/current
SB_CONFIG=$HOME/.config/second-brain/config.toml
J_START="node $J_CURRENT/dist/src/cli.js service run --db $AUTH_DB"
```

config.toml `state_root`를 바꿔도 **`request_root`는 자동으로 따라가지 않음**. 미설정 시 `request_root=$XDG_STATE_HOME/second-brain/requests` (기본). 격리 프로필은 `state_root`와 `request_root`를 둘 다 적는다.

lock: `$state_root/generation.lock` 및 같은 디렉터리 `generation-writer.lock` (`generation_locks.py`). generation.json 옆이 아님.

session-memory: `$state_root/.sb/session-memory`

## 관측 (stop 전, 전환 조건 아님)

`readlink -f $SB_CURRENT`; `readlink -f $J_CURRENT`; `which -a sb`
`systemctl --user is-active jm-jarvis.service jm-jarvis-dashboard.service jm-jarvis-phone-gateway.service jm-second-brain-requests.service jm-second-brain-refresh.service jm-second-brain-refresh.timer`
`python3 deploy/check-jarvis-pending-state.py "$AUTH_DB"`
`python3 deploy/check-database-handles.py "$AUTH_DB"`

## stop (승인 후)

`systemctl --user stop jm-jarvis.service jm-jarvis-dashboard.service jm-jarvis-phone-gateway.service jm-second-brain-refresh.timer jm-second-brain-refresh.service jm-second-brain-requests.service second-brain.service`

**stop 후 사후조건 (하나라도 실패면 current 금지, 정지 유지):**
- `check-database-handles.py "$AUTH_DB"` EXIT0
- `check-jarvis-pending-state.py "$AUTH_DB"` 관측 (drain_authorized 항상 false)
- `$state_root/generation-writer.lock` 홀더 없음

## current 교체

`ln -sfn <SB후보절대경로> $SB_CURRENT`
`ln -sfn <J후보절대경로> $J_CURRENT`

PATH `sb` (`second-brain.service` PATH=`%h/.local/bin:...`)는 `$SB_CURRENT/bin/sb`와 다를 수 있음. 요청 유닛만 current/bin/sb.

**부분 전환:** SB ln 성공·J ln 실패는 “이전 current 유지”가 아님. SB는 새 후보, J는 옛 current. 이 상태에서 start 금지. J ln을 완료하거나, 당일 기록한 **SB 이전 절대 경로**로 SB만 되돌릴지는 별도 승인. 구버전 바이너리 start / revoked `41f0751` 복귀 금지.

## start

새 `$SB_CURRENT/bin/sb` 및 `$J_START`만. 성공: `$SB_CURRENT/bin/sb doctor`; 합의 서비스 active; `$SB_CURRENT/bin/sb search` 1건; `/var/tmp/jarvis-artifact-64715ba/bin/jarvis --help` 0.

실패: 정지 유지. `sb restore <archive> --to <격리경로>` 후 **같은 새 릴리스** start. `--force` 당일 승인 없이 금지.

보류 수명 미검증. oneshot requests는 설계.
