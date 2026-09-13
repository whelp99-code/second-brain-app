# 현재 후보 운영 판단 (읽기 전용, 미실행)

전환·restore·rollback을 실행하지 않는다.

## 공개 유닛 경로

JARVIS (`deploy/jm-jarvis.service`):

- 바이너리: `WorkingDirectory=/home/jm/.local/state/orca-jarvis/authority/current`
- DB: `--db /home/jm/.local/state/orca-jarvis/jarvis.sqlite` (**current 아래가 아님**)
- start: `node …/authority/current/dist/src/cli.js service run --db /home/jm/.local/state/orca-jarvis/jarvis.sqlite`
- 제출 런타임 확인만: `/var/tmp/jarvis-artifact-64715ba/bin/jarvis --help` (78e7307 구핀 아님)

SB:

- 후보/운영 바이너리: `/home/jm/.local/state/second-brain/app/current/bin/sb`
- `jm-second-brain-requests.service`: `WorkingDirectory=…/app/current`, `ExecStart=…/app/current/bin/sb apply-requests --once`, `SB_CONFIG=/home/jm/.config/second-brain/config.toml`
- `deploy/systemd/second-brain.service` (`sb run`): `PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin` 의 **PATH `sb`**. current 교체가 `~/.local/bin/sb`를 바꾸지 않으면 이 유닛은 옛 바이너리를 씀.
- `jm-second-brain-refresh.service`: `EnvironmentFile=%h/.config/jm-second-brain/refresh.env`, `ExecStart=${SECOND_BRAIN_REFRESH_ENTRYPOINT}`, `ReadWritePaths=%h/.local/state/second-brain`, timer `OnCalendar=*-*-* 07:00:00 Asia/Seoul`
- config: `SB_CONFIG` vault_root / **state_root** (`XDG_STATE_HOME/second-brain` 기본) / request_root=`$state_root/requests` / share_root / generation_root
- session-memory: **state_root/.sb/session-memory** (generation/vault 봉인 경로 아님)
- journal: `$request_root/journal.db`
- generation locks: `generation.lock` 및 옆 `generation-writer.lock` (`sb/generation_locks.py`; generation.json과 같은 디렉터리)

```
AUTH_DB=/home/jm/.local/state/orca-jarvis/jarvis.sqlite
SB_CURRENT=/home/jm/.local/state/second-brain/app/current
SB_CONFIG=$HOME/.config/second-brain/config.toml
```

## 순서 (승인 후)

1. 기록: `readlink -f $SB_CURRENT`; `readlink -f /home/jm/.local/state/orca-jarvis/authority/current`; `which -a sb`; `systemctl --user is-active jm-jarvis.service jm-jarvis-dashboard.service jm-jarvis-phone-gateway.service jm-second-brain-requests.service jm-second-brain-refresh.timer`
2. stop 전 pending/handles는 **관측만**. handles 0을 stop 전 전환 조건으로 쓰지 않음. `python3 deploy/check-jarvis-pending-state.py "$AUTH_DB"`; `python3 deploy/check-database-handles.py "$AUTH_DB"`
3. stop: jarvis 세 유닛 + 당일 active인 `jm-second-brain-refresh.service` / `second-brain.service` / `jm-second-brain-requests.service`
4. **stop 후** `check-database-handles.py "$AUTH_DB"` EXIT0이 아니면 current를 바꾸지 않음. 정지 상태 유지.
5. `ln -sfn <후보-절대경로> $SB_CURRENT` 및 JARVIS `authority/current`. 운영 config 복사 금지.
6. start는 **새 current 바이너리 절대 경로**. PATH `sb` 유닛은 current와 다를 수 있음 — 당일 합의 없이 `~/.local/bin/sb`를 바꾸지 않음.

성공: `$SB_CURRENT/bin/sb doctor`; 합의된 서비스 active; `$SB_CURRENT/bin/sb search` 1건; `/var/tmp/jarvis-artifact-64715ba/bin/jarvis --help` 0.

## 실패 시 (CUTOVER-RUNBOOK)

구버전 current/구버전 바이너리 start 금지 (`41f0751` revoked key).

| 단계 | 상태 | 복구 |
|---|---|---|
| 4 handles 잔여 | 정지, current 미변경 | start 금지 |
| 5 ln 실패 | 이전 current 유지 | 새 current 없음 |
| 6 start/doctor 실패 | 새 current일 수 있음, 서비스 정지 | 새 바이너리 유지. `sb restore <archive> --to <격리경로>` 후 **같은 새 릴리스** start. `--force`는 당일 승인 없이 쓰지 않음 |

보류 수명 미검증. oneshot requests / timer not-found는 설계.
