# 현재 후보 운영 판단 (읽기 전용, 미실행)

전환·restore·rollback·lock/보류 검사를 실행하지 않는다. 리포 예시 / 설치 unit 파일 읽기 / 제안은 칸을 나눈다. 설치 unit **활성 상태**는 주장하지 않는다.

## 핀 구분

| 역할 | 값 |
|---|---|
| 제품 소스 | `a41b70d` |
| 테스트 전용 | `e0b3445` (chmod 제거; 제품 바이트 아님) |
| SB 격리 후보 | `/var/tmp/sb-candidate-a41b70d/releases/c9bdc5dd520b0e3908207cf34f319799e48bb19a` |
| 실행 게이트 로그 핀 | `/var/tmp/sb-gates-f7c1945.log` — **이 후보가 아님** |
| J 격리 런타임 | `/var/tmp/jarvis-artifact-64715ba` (`bin/jarvis --help`) |
| 운영 current (인용만) | SB `41f0751…`, J authority `a3cbbbe…` |

## 변수 (공개 리포)

```
AUTH_DB=/home/jm/.local/state/orca-jarvis/jarvis.sqlite
J_CURRENT=/home/jm/.local/state/orca-jarvis/authority/current
SB_CURRENT=/home/jm/.local/state/second-brain/app/current
SB_CONFIG=%h/.config/second-brain/config.toml
SB_CANDIDATE=/var/tmp/sb-candidate-a41b70d/releases/c9bdc5dd520b0e3908207cf34f319799e48bb19a
J_RUNTIME=/var/tmp/jarvis-artifact-64715ba
```

`state_root`를 바꿔도 `request_root`는 따라가지 않음 (`sb/config.py`). 미설정 시 `request_root=$XDG_STATE_HOME/second-brain/requests`.

lock (코드): 실행 root `vault_root/.sb/run.lock`; `$state_root/generation.lock` + `generation-writer.lock`.

J **런타임 산출물** (`J_RUNTIME`) ≠ **authority current** (`J_CURRENT`). 공개 `deploy/jm-jarvis.service`는 `node $J_CURRENT/dist/src/cli.js service run --db $AUTH_DB`. `--help` 확인은 `J_RUNTIME/bin/jarvis`이며 서비스 기동이 아니다.

## 공개 리포 unit (예시, 설치 주장 아님)

출처: `second-brain-app/systemd/user/` 파일 읽기.

| 유닛 | 파일 | 기동/인자 |
|---|---|---|
| `jm-second-brain-requests.path` | `systemd/user/jm-second-brain-requests.path:5` | **PathChanged**=`%h/.local/state/second-brain/requests/pending`. 디렉터리 **내용 변경**이지 “비어 있지 않음”이 아님. 비게 되는 변경도 해당. |
| `jm-second-brain-requests.service` | `systemd/user/jm-second-brain-requests.service:3,7–8` | **ConditionPathIsDirectory**=같은 pending 경로. `ExecStart=/usr/bin/env sb apply-requests --once`. **PATH의 `sb`**. `Environment=SB_CONFIG=%h/.config/second-brain/config.toml`. current 절대 경로 아님. |
| `second-brain.service` | `deploy/systemd/second-brain.service` | `PATH=%h/.local/bin:…` 의 `sb run`. current/bin과 다를 수 있음. |
| `second-brain.timer` | `deploy/systemd/second-brain.timer` | hourly → `second-brain.service` |
| `jm-second-brain-refresh.timer` | `Orca-JARVIS/deploy/jm-second-brain-refresh.timer` | 07:00 Asia/Seoul → refresh.service |
| `jm-jarvis.service` | `Orca-JARVIS/deploy/jm-jarvis.service` | `node $J_CURRENT/dist/src/cli.js service run --db $AUTH_DB` |

## 설치 unit 파일 읽기 (활성 상태 비주장)

시각: 2026-09-13 파일 읽기. `~/.config/systemd/user/jm-second-brain-requests.path` / `.service`는 리포와 **다를 수 있음**(DirectoryNotEmpty, `$SB_CURRENT/bin/sb`). 이 칸은 리포 표와 섞지 않는다. 당일 기동 여부는 **외부 슬롯** `installed_unit_active_state` (미관측).

## 관측 슬롯 (미실행)

`readlink -f $SB_CURRENT $J_CURRENT`; `which -a sb`
`systemctl --user is-active` — 당일 슬롯 `unit_active_set`
`python3 deploy/check-jarvis-pending-state.py "$AUTH_DB"` → `states`, `counts.active_cursor_rows`, `counts.cursor_rows`, `leases.*.unexpired`, `leases.*.invalid`, `drain_authorized`
`python3 deploy/check-database-handles.py "$AUTH_DB"` → 홀더 목록

## stop (승인 후, 지금 실행 금지)

리포 기준 stop 대상 이름: `jm-jarvis.service` `jm-jarvis-dashboard.service` `jm-jarvis-phone-gateway.service` `jm-second-brain-refresh.timer` `jm-second-brain-refresh.service` `jm-second-brain-requests.path` `jm-second-brain-requests.service` `second-brain.timer` `second-brain.service`

**사후조건 (미해결이면 current 금지·정지 유지).** `drain_authorized: false`는 허가 아님.

미해결/미확정으로 취급할 슬롯:
- pending `states` 비어 있지 않음
- `counts.active_cursor_rows` ≠ 0 또는 미관측
- `leases.gjc_runtime_leases.unexpired` 또는 `.invalid` > 0 (또는 microloop 동등)
- handles 홀더 있음 / 도구 미실행
- `generation-writer.lock` 또는 실행 root `.sb/run.lock` 홀더 미관측

필요 입력(이름만): `pending_state_json`, `handles_json`, `writer_lock_holders`.

## current / 부분 전환

`ln -sfn $SB_CANDIDATE $SB_CURRENT`
`ln -sfn <J_AUTHORITY_RELEASE_절대경로> $J_CURRENT` — **J_RUNTIME을 authority current로 쓰지 않음** (슬롯 `j_authority_release_path`).

| 상태 | 의미 | 기동 |
|---|---|---|
| SB ln 성공·J 실패 | SB=후보, J=옛 current. 이전 양쪽 current 유지가 아님 | 금지 |
| J ln 성공·SB 실패 | 대칭 | 금지 |
| 둘 다 실패 | 양쪽 옛 current | 금지 |

## restore 후 (미실행)

`sb restore <archive> --to <격리경로>`
격리 트리는 자체 config를 소비: `vault_root` / `state_root` / `request_root` (후자는 자동 아님). 검증 전 writer 정지. 검증 성공 ≠ 운영 승인. 실패 시 정지 유지. `--force` 슬롯 `restore_force_authorized` 기본 false.

start (운영 승인 후): 새 `$SB_CURRENT/bin/sb` 및 `$J_CURRENT` 서비스만. 성공 슬롯: `sb_doctor_exit`, `sb_search_one_hit`, `j_service_active`, `J_RUNTIME/bin/jarvis --help` 0 (도움말은 서비스 기동 아님).

보류 수명 미검증. N1 native/in-turn 한계 유지.
