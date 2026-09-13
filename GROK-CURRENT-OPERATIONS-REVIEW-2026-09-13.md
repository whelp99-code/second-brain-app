# 현재 후보 운영 판단 (읽기 전용, 미실행)

전환·restore·rollback·lock/보류 검사를 실행하지 않는다.

## 핀

| 역할 | 값 |
|---|---|
| 제품 | 이번 훅 커밋 |
| SB 후보 | 이번 prepare-release 경로 |
| J 런타임 | `/var/tmp/jarvis-artifact-64715ba` ≠ `J_CURRENT` |
| 게이트 로그 | `/var/tmp/sb-gates-f7c1945.log` 이 후보 아님 |
| 운영 current 인용 | SB `41f0751…`, J authority `a3cbbbe…` |

```
AUTH_DB=/home/jm/.local/state/orca-jarvis/jarvis.sqlite
J_CURRENT=/home/jm/.local/state/orca-jarvis/authority/current
SB_CURRENT=/home/jm/.local/state/second-brain/app/current
USER_CONFIG=/home/jm/.config/second-brain/config.toml
```

config 탐색 순서 (`sb/config.py:184-192`): `SB_CONFIG` 환경 → `user_config_path()` 파일이 있으면 그것 → `APP_ROOT/config.toml` 파일이 있으면 그것 → 아니면 user_path. 리포 `systemd/user/jm-second-brain-requests.service` 행에 SB_CONFIG를 적지 않는다. 설치 파일 읽기(2026-09-13, 활성 비주장): `Environment=SB_CONFIG=/home/jm/.config/second-brain/config.toml`.

`state_root` ≠ `request_root`. 미설정 `request_root=$XDG_STATE_HOME/second-brain/requests`.
lock: 실행 root `vault_root/.sb/run.lock`; `$state_root/generation.lock` + `generation-writer.lock`.

공개 `deploy/jm-jarvis.service`: `node $J_CURRENT/dist/src/cli.js service run --db $AUTH_DB`. `J_RUNTIME/bin/jarvis --help`는 기동이 아님.

## D1 inspect()

`inspect()`는 naive `observed_at`이면 `ValueError("timezone-aware observation time required")`. CLI `main()`은 `inspect(args.database)`만 호출하고 기본 `now=datetime.now(UTC)`라 **aware UTC**. naive `datetime.now()` 프로브는 CLI가 아님. 도구 미실행.

## D2 리포 / 설치 파일 / 제안

**리포 예시** (`second-brain-app/systemd/user/`):
- path:5 **PathChanged**=`%h/.local/state/second-brain/requests/pending` — 내용 변경(비게 되는 변경 포함).
- service:3,7–8 **ConditionPathIsDirectory** 같은 pending. `ExecStart=/usr/bin/env sb apply-requests --once` (**PATH `sb`**).

**설치 파일 읽기** (2026-09-13, 활성 비주장):
- path: `ConditionPathExists=/home/jm/.config/second-brain/request-executor.enabled`, **DirectoryNotEmpty**=`/home/jm/.local/state/second-brain/requests/pending`
- service: `WorkingDirectory=$SB_CURRENT`, `ExecStart=$SB_CURRENT/bin/sb apply-requests --once`
- drop-in `20-runtime.conf`: `PATH=$SB_CURRENT/bin:…`
- 슬롯 `installed_unit_active_state`

**제안:** 없음.

## D3 정지 / 부분 전환 / restore

stop 이름: `jm-jarvis.service` `jm-jarvis-dashboard.service` `jm-jarvis-phone-gateway.service` `jm-second-brain-refresh.timer` `jm-second-brain-refresh.service` `jm-second-brain-requests.path` `jm-second-brain-requests.service` `second-brain.timer` `second-brain.service`

판정표 (`inspect()` 키, 미실행):

| 키 | 정지 후 current 금지 |
|---|---|
| `states.memory_outbox` / `gjc_runtime` / `gjc_runtime_leases` / `gjc_intents` / `gjc_intent_leases` / `gjc_microloop_leases` | 해당 테이블 행이 있으면 금지 |
| `counts.cursor_rows` `active_cursor_rows` `unexpired_lease_rows` `invalid_lease_rows` | `active_cursor_rows`≠0 또는 unexpired/invalid>0 또는 미관측 |
| `leases.*.unexpired` / `.invalid` | >0 또는 미관측 |
| `drain_authorized` | **항상 false**. 허가로 쓰지 않음 |
| handles | 홀더 있으면 금지 |

슬롯: `pending_state_json`, `handles_json`, `writer_lock_holders`.

current: `ln -sfn $SB_CANDIDATE $SB_CURRENT`; `ln -sfn $J_AUTHORITY_RELEASE $J_CURRENT` (**J_RUNTIME 금지**).

부분: SB만 성공 = SB=후보·J=옛. 이전 양쪽 유지가 아님. start 금지.

restore 슬롯:
- `RESTORED_ROOT` — `sb restore <archive> --to $RESTORED_ROOT`
- 격리 config: `$RESTORED_ROOT` 쪽 `vault_root`/`state_root`/`request_root` (자동 아님)
- `VERIFY_CONFIG` — 검증에 쓰는 config 경로
- `VERIFY_DOCTOR` — 예: `SB_CONFIG=$VERIFY_CONFIG $SB_CANDIDATE/bin/sb doctor`
- `VERIFY_SEARCH` — 예: `SB_CONFIG=$VERIFY_CONFIG $SB_CANDIDATE/bin/sb search '<query>'`
검증 전 writer 정지. 검증 성공 ≠ 운영 승인. `--force` 슬롯 `restore_force_authorized` 기본 false.

보류 수명 미검증.
