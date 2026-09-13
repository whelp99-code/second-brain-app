# 현재 후보 운영 판단 (읽기 전용, 미실행)

전환·restore·rollback·lock/보류 검사를 실행하지 않는다.

## 핀

| 역할 | 값 |
|---|---|
| 제품 | `a41b70d` |
| 테스트 전용 | `e0b3445` |
| SB 후보 | `/var/tmp/sb-candidate-a41b70d/releases/c9bdc5dd520b0e3908207cf34f319799e48bb19a` |
| 게이트 로그 | `/var/tmp/sb-gates-f7c1945.log` — 이 후보 아님 |
| J 런타임 | `/var/tmp/jarvis-artifact-64715ba` — **authority current 아님** |
| 운영 current 인용 | SB `41f0751…`, J authority `a3cbbbe…` |

```
AUTH_DB=/home/jm/.local/state/orca-jarvis/jarvis.sqlite
J_CURRENT=/home/jm/.local/state/orca-jarvis/authority/current
SB_CURRENT=/home/jm/.local/state/second-brain/app/current
SB_CONFIG=%h/.config/second-brain/config.toml
SB_CANDIDATE=/var/tmp/sb-candidate-a41b70d/releases/c9bdc5dd520b0e3908207cf34f319799e48bb19a
J_RUNTIME=/var/tmp/jarvis-artifact-64715ba
```

`state_root` ≠ `request_root` (`sb/config.py`). 미설정 `request_root=$XDG_STATE_HOME/second-brain/requests`.
lock: 실행 root `vault_root/.sb/run.lock`; `$state_root/generation.lock` + `generation-writer.lock`.

공개 `deploy/jm-jarvis.service`: `node $J_CURRENT/dist/src/cli.js service run --db $AUTH_DB`. `J_RUNTIME/bin/jarvis --help`는 서비스 기동이 아님.

## D1 inspect() 시간대

`deploy/check-jarvis-pending-state.py` `inspect()`는 `observed_at.tzinfo is None`이면 `ValueError("timezone-aware observation time required")`. CLI `main()`은 `inspect(args.database)`만 호출하며 기본 `now=datetime.now(UTC)`라 **aware UTC**다. naive `datetime.now()`를 넘긴 프로브는 CLI와 다르다. 이 문서는 도구를 실행하지 않음.

`inspect()` 출력 키: `states` (`memory_outbox`,`gjc_runtime`,`gjc_runtime_leases`,`gjc_intents`,`gjc_intent_leases`,`gjc_microloop_leases`), `counts` (`cursor_rows`,`active_cursor_rows`,`unexpired_lease_rows`), `leases.*.unexpired` / `.invalid`, `drain_authorized` (**항상 false**, 허가 아님).

## D2 리포 / 설치 파일 / 제안 (세 칸)

**리포 예시** (`second-brain-app/systemd/user/`, 설치 주장 아님):
- `jm-second-brain-requests.path:5` **PathChanged**=`%h/.local/state/second-brain/requests/pending` — 내용 변경(비게 되는 변경 포함). “비어 있지 않음”이 아님.
- `jm-second-brain-requests.service:3,7–8` **ConditionPathIsDirectory** 같은 pending 경로. `ExecStart=/usr/bin/env sb apply-requests --once` (**PATH `sb`**). `SB_CONFIG=%h/.config/second-brain/config.toml`.

**설치 unit 파일 읽기** (2026-09-13, **활성 상태 비주장**):
- `~/.config/systemd/user/jm-second-brain-requests.path`: `ConditionPathExists=/home/jm/.config/second-brain/request-executor.enabled`, **DirectoryNotEmpty**=`/home/jm/.local/state/second-brain/requests/pending` (리포 PathChanged와 다름).
- `~/.config/systemd/user/jm-second-brain-requests.service`: `WorkingDirectory=$SB_CURRENT`, `ExecStart=$SB_CURRENT/bin/sb apply-requests --once`, `Environment=SB_CONFIG=/home/jm/.config/second-brain/config.toml`.
- drop-in `jm-second-brain-requests.service.d/20-runtime.conf`: `PATH=$SB_CURRENT/bin:…` 를 PATH 앞에 둠. 기동은 절대 `bin/sb`이며 PATH 보강은 drop-in.
- 당일 active 여부는 슬롯 `installed_unit_active_state` (미관측).

**제안:** 없음. 이 문서는 unit을 바꾸지 않음.

기타 리포: `second-brain.service` PATH `sb run`; `second-brain.timer` hourly; refresh.timer 07:00 Asia/Seoul.

## D3 정지 조건 / 부분 전환 / restore

stop 대상 이름: `jm-jarvis.service` `jm-jarvis-dashboard.service` `jm-jarvis-phone-gateway.service` `jm-second-brain-refresh.timer` `jm-second-brain-refresh.service` `jm-second-brain-requests.path` `jm-second-brain-requests.service` `second-brain.timer` `second-brain.service`

사후 **미해결이면 current 금지·정지 유지** (`drain_authorized: false` ≠ 허가):
- `states` 비어 있지 않음
- `counts.active_cursor_rows` ≠ 0 또는 미관측
- `leases.*.unexpired` 또는 `.invalid` > 0
- handles 홀더 / 미실행
- `generation-writer.lock` 또는 `.sb/run.lock` 홀더 미관측

슬롯: `pending_state_json`, `handles_json`, `writer_lock_holders`.

current: `ln -sfn $SB_CANDIDATE $SB_CURRENT`; `ln -sfn <j_authority_release_path> $J_CURRENT` (**J_RUNTIME을 current로 쓰지 않음**).

| 부분 상태 | 의미 | 기동 |
|---|---|---|
| SB ln 성공·J 실패 | SB=후보, J=옛. 양쪽 이전 current 유지가 아님 | 금지 |
| J ln 성공·SB 실패 | 대칭 | 금지 |

restore: `sb restore <archive> --to <격리경로>`. 격리 config `vault_root`/`state_root`/`request_root` 소비. 검증 전 writer 정지. 검증 성공 ≠ 운영 승인. `--force` 슬롯 `restore_force_authorized` 기본 false.

start (운영 승인 후): 새 `$SB_CURRENT/bin/sb`, `$J_CURRENT` 서비스. 성공 슬롯 `sb_doctor_exit`, `sb_search_one_hit`, `j_service_active`. `J_RUNTIME/bin/jarvis --help`는 기동 아님.

보류 수명 미검증.
