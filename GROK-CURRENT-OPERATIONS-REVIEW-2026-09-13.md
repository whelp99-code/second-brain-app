# 현재 후보 운영 판단 (읽기 전용, 미실행)

전환·rollback·보류 검증을 실행하지 않는다. 당일 PID/백업 hash는 점검 대기.

## 공개 유닛이 가리키는 경로

JARVIS 서비스 (`Orca-JARVIS/deploy/jm-jarvis.service`):

- WorkingDirectory `/home/jm/.local/state/orca-jarvis/authority/current` (바이너리/dist)
- `--db /home/jm/.local/state/orca-jarvis/jarvis.sqlite` — **release 디렉터리 아래가 아님. `current/jarvis-authority.sqlite`가 아님.**
- 백업 유닛도 같은 `--db` (`jm-jarvis-backup.service`)

SB 유닛 (`deploy/systemd/second-brain.service`):

- `SB_CONFIG=%h/.config/second-brain/config.toml`
- `ReadWritePaths`: `%h/.local/share/second-brain` `%h/.local/state/second-brain` `%h/.config/second-brain`
- `ExecStart=sb run` (writer). 후보 바이너리는 `/home/jm/.local/state/second-brain/app/current/bin/sb`

```
AUTH_DB=/home/jm/.local/state/orca-jarvis/jarvis.sqlite
SB_CURRENT=/home/jm/.local/state/second-brain/app/current
SB_CONFIG=$HOME/.config/second-brain/config.toml
```

`AUTH_DB`를 `find "$AUTH/current" -name '*.sqlite'`로 대체하지 않는다.

## 순서 (승인 후; 지금 실행 금지)

1. 기록: `readlink -f $SB_CURRENT`; `readlink -f /home/jm/.local/state/orca-jarvis/authority/current`; `systemctl --user is-active jm-jarvis.service jm-jarvis-dashboard.service jm-jarvis-phone-gateway.service`; 백업 경로/hash.
2. **실행 중 writer 관측** (stop 전 handles 0을 전환 조건으로 쓰지 않음): `python3 deploy/check-jarvis-pending-state.py "$AUTH_DB"`; `python3 deploy/check-database-handles.py "$AUTH_DB"`. 결과는 관측. `drain_authorized`는 항상 false.
3. `systemctl --user stop jm-jarvis.service jm-jarvis-dashboard.service jm-jarvis-phone-gateway.service` (및 당일 활성 SB writer: `jm-second-brain-refresh.service` / `second-brain.service`가 active면 stop).
4. **stop 후** handles: `python3 deploy/check-database-handles.py "$AUTH_DB"` EXIT0 (홀더 없음)이 아니면 current를 바꾸지 않음.
5. `ln -sfn`으로 `$SB_CURRENT`와 JARVIS `authority/current`를 **새 후보 절대 경로**로. 운영 `~/.config/second-brain` / `~/.claude`는 건드리지 않음.
6. start는 **새 릴리스 바이너리**만.

성공: 새 `bin/sb doctor` (격리 `SB_CONFIG`가 아니라 당일 합의된 config), 세 서비스 active, search 1건, `/var/tmp/jarvis-artifact-78e7307/bin/jarvis --help` 0.

## 실패 복구 (CUTOVER-RUNBOOK 제약)

**구버전 current 링크 복원 / 구버전 바이너리 start는 금지.** `41f0751`은 `revoked-jarvis-signing-key-ids`를 읽지 않는다.

| 단계 | 복구 |
|---|---|
| 4 handles 잔여 | current 유지. start 하지 않음 |
| 5 ln 실패 | 새 current를 만들지 않음 |
| 6 start/doctor 실패 | 새 바이너리 유지. 검증된 백업을 `sb restore --to`로 **격리** 복원 후 **같은 새 릴리스**로 start. 부분 sqlite만 되돌리지 않음 |

보류 보안/삭제/경합/복원 수명은 미검증. oneshot requests / timer not-found는 설계.
