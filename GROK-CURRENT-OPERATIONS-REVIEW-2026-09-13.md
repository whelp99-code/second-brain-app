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

config 탐색 (`sb/config.py:184-192`): `SB_CONFIG` → `user_config_path()` 파일 → `APP_ROOT/config.toml` 파일 → 아니면 user_path.
`state_root` ≠ `request_root`. lock: 실행 root `vault_root/.sb/run.lock`; `$state_root/generation.lock` + `generation-writer.lock`.
공개 `deploy/jm-jarvis.service`: `node $J_CURRENT/dist/src/cli.js service run --db $AUTH_DB`.

## D1 inspect()

CLI `inspect(args.database)` 기본 `now=datetime.now(UTC)`. naive now 프로브는 CLI가 아님. 도구 미실행.

## D2 리포 / 설치 파일 / 제안

**리포 예시** (`systemd/user/`): PathChanged pending; ConditionPathIsDirectory; `ExecStart=/usr/bin/env sb apply-requests --once`.

**설치 파일 읽기** (2026-09-13 파일 읽기, **활성 상태 비주장**):
- `~/.config/systemd/user/jm-second-brain-requests.path`: `ConditionPathExists=/home/jm/.config/second-brain/request-executor.enabled`; `DirectoryNotEmpty=/home/jm/.local/state/second-brain/requests/pending`
- `~/.config/systemd/user/jm-second-brain-requests.service`: `WorkingDirectory=/home/jm/.local/state/second-brain/app/current`; `ExecStart=/home/jm/.local/state/second-brain/app/current/bin/sb apply-requests --once`; `Environment=SB_CONFIG=/home/jm/.config/second-brain/config.toml`
- drop-in `jm-second-brain-requests.service.d/20-runtime.conf`: `PATH` 앞에 `$SB_CURRENT/bin`
- 슬롯 `installed_unit_active_state`

**제안:** 없음.

판정표 (`inspect()` 키, 미실행). `{table: []}`는 행 없음. `count>0`만 미해결로 본다.

| 테이블 | unresolved (정지·current 금지) | terminal (통과) | 미분류 |
|---|---|---|---|
| `memory_outbox` | `queued`, `delivering`, `accepted_unsettled`, `uncertain` | `settled`, `expired` | 그 외 값 → 정지 |
| `memory_outbox_attempts` | 행 있음 | 빈 배열 | 미관측 → 정지 |
| `memory_candidate_dispatch_publications` | 행 있음 | 빈 배열 | 미관측 → 정지 |
| `collaboration_bridge_outbox` | 행 있음 | 빈 배열 | 미관측 → 정지 |
| `pre_gjc_report_outbox` | 행 있음 | 빈 배열 | 미관측 → 정지 |
| `outbox` | 행 있음 | 빈 배열 | 미관측 → 정지 |

`counts`: `cursor_rows`, `active_cursor_rows`, `gjc_lease_rows`, `microloop_lease_rows`. `active_cursor_rows≠0` 또는 lease_rows>0 또는 미관측 → 정지.
`leases`: `gjc_runtime_leases`, `microloop_leases`. unexpired/invalid >0 또는 미관측 → 정지.
`drain_authorized` 항상 false. 허가 아님.

## D3 restore 슬롯

```
RESTORED_ROOT
VERIFY_CONFIG
VERIFY_STATE_ROOT
VERIFY_REQUEST_ROOT
VERIFY_QUERY
VERIFY_DOCTOR
VERIFY_SEARCH
```

| 슬롯 | 매핑 |
|---|---|
| `RESTORED_ROOT` | `sb restore <archive> --to $RESTORED_ROOT` |
| `VERIFY_CONFIG` | 격리 config 경로 |
| `VERIFY_STATE_ROOT` | 그 config의 `state_root` (자동 아님) |
| `VERIFY_REQUEST_ROOT` | 그 config의 `request_root` (자동 아님) |
| `VERIFY_QUERY` | 검증 검색어 |
| `VERIFY_DOCTOR` | `SB_CONFIG=$VERIFY_CONFIG $SB_CANDIDATE/bin/sb doctor` |
| `VERIFY_SEARCH` | `SB_CONFIG=$VERIFY_CONFIG $SB_CANDIDATE/bin/sb search "$VERIFY_QUERY"` |

검증 전 writer 정지. 검증 성공 ≠ 운영 승인. `--force` 슬롯 `restore_force_authorized` 기본 false.
부분 전환: SB만 성공 = SB=후보·J=옛. start 금지.
